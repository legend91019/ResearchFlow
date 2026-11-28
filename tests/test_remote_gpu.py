from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tarfile
import pytest

from scripts import remote_gpu


def test_parse_ssh_command_variants() -> None:
    ep = remote_gpu.parse_ssh_command("ssh -p 51263 root@connect.bjb1.seetacloud.com")
    assert ep.host == "connect.bjb1.seetacloud.com"
    assert ep.port == 51263
    assert ep.user == "root"

    ep2 = remote_gpu.parse_ssh_command("ssh -i ~/.ssh/my_key -p2222 ubuntu@10.0.0.8")
    assert ep2.host == "10.0.0.8"
    assert ep2.port == 2222
    assert ep2.user == "ubuntu"
    assert ep2.identity_file == "~/.ssh/my_key"

    ep3 = remote_gpu.parse_ssh_command("alice@gpu.lab.edu:6006")
    assert ep3.host == "gpu.lab.edu"
    assert ep3.port == 6006
    assert ep3.user == "alice"


def test_tar_pack_excludes_and_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "exp_code"
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__" / "junk.pyc").write_bytes(b"123")
    (src / ".git").mkdir()
    (src / ".git" / "config").write_text("secret", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (src / "sub" / "cfg.json").write_text('{"lr": 1e-4}\n', encoding="utf-8")

    tar_bytes, included = remote_gpu.build_tar_bytes(src, extra_excludes=("*.tmp",))
    assert included == ["run.py", "sub/cfg.json"]

    dest = tmp_path / "unpacked"
    extracted = remote_gpu.safe_extract_tar_bytes(tar_bytes, dest)
    assert sorted(extracted) == ["run.py", "sub/cfg.json"]
    assert (dest / "run.py").read_text(encoding="utf-8") == "print('ok')\n"


def test_safe_extract_blocks_tar_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="../evil.txt")
        payload = b"pwned"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="Unsafe path"):
        remote_gpu.safe_extract_tar_bytes(buf.getvalue(), tmp_path / "out")


def test_launch_script_sets_cache_and_exit_code() -> None:
    script = remote_gpu.build_launch_script(
        remote_dir="/root/autodl-tmp/rf_exp",
        job_id="gate0_run",
        command="python run_gate0.py --seed 42",
        workdir_rel="gate0_pilot",
        gpu_devices="0",
    )
    assert "HF_HOME=" in script
    assert "TMPDIR=" in script
    assert "PIP_CACHE_DIR=" in script
    assert "MODELSCOPE_CACHE=" in script
    assert "CUDA_VISIBLE_DEVICES=0" in script
    assert "/root/autodl-tmp/rf_exp/.rf_jobs/gate0_run/exit_code" in script
    assert "nohup setsid bash" in script


def test_exec_streams_python_script_over_stdin(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    script_file = tmp_path / "quick_check.py"
    script_file.write_text("import os\nprint('quote_safe:', \"a'b\\\"c\")\n", encoding="utf-8")
    remote_gpu.save_profile(
        ws,
        remote_gpu.RemoteProfile(
            host="gpu.example.com",
            port=44,
            user="znsoft",
            key_path=str(ws / ".ssh" / "id_ed25519"),
            remote_dir="/home/znsoft/rf_ws",
        ),
    )

    captured: list[tuple[str, bytes]] = []

    def fake_runner(
        profile: remote_gpu.RemoteProfile,
        remote_cmd: str,
        stdin_bytes: bytes | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[bytes]:
        captured.append((remote_cmd, stdin_bytes or b""))
        return subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout=b"quote_safe: a'b\"c\n", stderr=b"")

    parser = remote_gpu.build_parser()
    out = remote_gpu.cmd_exec(
        parser.parse_args(["exec", "--workspace", str(ws), "--script", str(script_file), "--gpu", "0"]),
        runner=fake_runner,
    )
    assert out["status"] == "ok"
    assert "python3 -" in captured[0][0]
    assert "TMPDIR=/home/znsoft/rf_ws/.cache/tmp" in captured[0][0]
    assert b"quote_safe:" in captured[0][1]


def test_status_enrichment_detects_oom_and_low_gpu_util() -> None:
    payload = {
        "exists": True,
        "state": "RUNNING",
        "pid": 1234,
        "alive": True,
        "exit_code": None,
        "gpus": [{"index": 0, "gpu_util_pct": 0, "vram_used_mb": 12000, "vram_total_mb": 24576}],
        "log_tail": "Step 10\nRuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
    }
    enriched = remote_gpu.enrich_status_payload(payload)
    assert "CUDA_OOM" in enriched["anomalies"]
    assert "LOW_GPU_UTIL_POSSIBLE_CPU_BOTTLENECK_OR_HANG" in enriched["anomalies"]


def test_push_and_status_with_mock_runner(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "train.py").write_text("x = 1\n", encoding="utf-8")
    remote_gpu.save_profile(
        ws,
        remote_gpu.RemoteProfile(
            host="example.com",
            port=51263,
            user="root",
            key_path=str(ws / ".ssh" / "id_ed25519"),
            remote_dir="/root/autodl-tmp/rf_ws",
        ),
    )

    calls: list[tuple[str, int]] = []

    def fake_runner(
        profile: remote_gpu.RemoteProfile,
        remote_cmd: str,
        stdin_bytes: bytes | None,
        timeout: int,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((remote_cmd, len(stdin_bytes or b"")))
        if "tar -xzf -" in remote_cmd:
            return subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout=b"", stderr=b"")
        mock_status = {
            "exists": True,
            "state": "COMPLETED",
            "pid": 999,
            "alive": False,
            "exit_code": 0,
            "gpus": [{"index": 0, "gpu_util_pct": 0, "vram_used_mb": 0, "vram_total_mb": 24576}],
            "log_tail": "All runs finished cleanly.",
            "progress": {"done": 16, "total": 16},
        }
        return subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout=json.dumps(mock_status).encode("utf-8"),
            stderr=b"",
        )

    parser = remote_gpu.build_parser()
    push_res = remote_gpu.cmd_push(
        parser.parse_args(["push", "--workspace", str(ws), "--src", "src"]),
        runner=fake_runner,
    )
    assert push_res["files_pushed"] == 1
    assert calls[0][1] > 0

    st_res = remote_gpu.cmd_status(
        parser.parse_args(["status", "--workspace", str(ws), "--job-id", "main_1", "--progress-file", "results/p.json"]),
        runner=fake_runner,
    )
    assert st_res["state"] == "COMPLETED"
    assert st_res["anomalies"] == []
    assert st_res["progress"]["done"] == 16
