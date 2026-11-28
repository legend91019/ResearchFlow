#!/usr/bin/env python3
"""Zero-dependency remote GPU synchronization, daemon launch, and status inspection CLI.

Designed for ResearchFlow's primary execution topology:
- Local host (Windows / macOS / Linux) manages research state, edits code, and audits results.
- Remote Linux GPU server (AutoDL, SeetaCloud, Featurize, lab cluster) runs heavy GPU jobs over SSH.

Core capabilities:
1. `init`   : Parse pasted SSH strings (`ssh -p 51263 root@host`), generate a workspace-scoped Ed25519
              keypair, and bootstrap passwordless SSH via `SSH_ASKPASS` (or optional `paramiko` fallback)
              without shell-escaping hazards on special password characters (`@`, `$`, `!`, `,`, quotes).
              Plaintext passwords are NEVER persisted to disk.
2. `probe`  : One-shot hardware & environment inspection (GPU model/VRAM/utilization, CPU/RAM, disk free
              across `/` vs data mounts like `/root/autodl-tmp`, Python/PyTorch/CUDA readiness).
3. `push`   : Fast, atomic directory/file upload via Python `tarfile` streamed over SSH (no `rsync` needed,
              auto-excludes `.git`, `__pycache__`, `.venv`, local `papers/*/repo/.git`, etc.).
4. `pull`   : Safe tar-stream download of remote `results/`, logs, or artifacts with path-traversal guards.
5. `launch` : Detached `nohup` + `setsid` background job runner that redirects HF/ModelScope/Torch caches
              away from small `/` root disks, logs PID/timestamps, and records exact process exit codes.
6. `status` : Single-roundtrip non-polling health check (job state `RUNNING`/`COMPLETED`/`FAILED`, live
              `nvidia-smi` telemetry, low-GPU-utilization stall warning, OOM/NaN/Traceback scan, and
              structured `progress.json` / `RUN_STATUS.json` snapshot).
7. `profile`: Live call-stack inspection (`py-spy dump` / `/proc/<pid>/wchan`) for stalled or CPU-bound jobs.
8. `kill`   : Clean process-group termination (`-TERM` then `-KILL`) so child CUDA processes never leak VRAM.

Zero third-party dependencies required (Python 3.10+ standard library + system OpenSSH `ssh`/`ssh-keygen`).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import fnmatch
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Callable

PROFILE_FILENAME = ".remote_host.json"
DEFAULT_EXCLUDES = (
    ".git",
    ".svn",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".pytest_tmp",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    ".ssh",
    ".remote_host.json",
    "node_modules",
)

FATAL_LOG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CUDA_OOM", re.compile(r"CUDA out of memory|OutOfMemoryError|CUBLAS_STATUS_ALLOC_FAILED", re.I)),
    ("TRACEBACK", re.compile(r"Traceback \(most recent call last\):")),
    ("NAN_INF", re.compile(r"\b(?:loss|grad|norm)\s*[=:]\s*(?:nan|inf|-inf)\b|NaN detected", re.I)),
    ("KILLED_OOM", re.compile(r"Killed\s*$|oom-kill|Out of memory:", re.M)),
    ("DISK_FULL", re.compile(r"No space left on device|Disk quota exceeded", re.I)),
)

SshRunner = Callable[["RemoteProfile", str, bytes | None, int], subprocess.CompletedProcess[bytes]]


@dataclass
class RemoteProfile:
    host: str
    port: int = 22
    user: str = "root"
    key_path: str = ""
    remote_dir: str = "/root/researchflow_run"
    created_at: str = ""

    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass
class ParsedSshEndpoint:
    host: str
    port: int = 22
    user: str = "root"
    identity_file: str = ""


def parse_ssh_command(raw: str) -> ParsedSshEndpoint:
    """Parse pasted SSH strings like `ssh -p 51263 root@connect.bjb1.seetacloud.com` or `user@host:2222`."""
    text = raw.strip()
    if not text:
        raise ValueError("Empty SSH connection string")

    tokens = shlex.split(text, posix=True)
    if tokens and tokens[0].lower() in {"ssh", "ssh.exe"}:
        tokens = tokens[1:]

    port = 22
    user = ""
    identity_file = ""
    destination = ""

    idx = 0
    flags_with_arg = {"-p", "-l", "-i", "-o", "-J", "-F", "-L", "-R", "-D", "-W", "-b", "-c", "-E", "-m", "-O", "-Q", "-S", "-w"}
    while idx < len(tokens):
        tok = tokens[idx]
        if tok == "-p" and idx + 1 < len(tokens):
            port = int(tokens[idx + 1])
            idx += 2
            continue
        if tok.startswith("-p") and len(tok) > 2 and tok[2:].isdigit():
            port = int(tok[2:])
            idx += 1
            continue
        if tok == "-l" and idx + 1 < len(tokens):
            user = tokens[idx + 1]
            idx += 2
            continue
        if tok == "-i" and idx + 1 < len(tokens):
            identity_file = tokens[idx + 1]
            idx += 2
            continue
        if tok in flags_with_arg and idx + 1 < len(tokens):
            idx += 2
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        if not destination:
            destination = tok
        idx += 1

    if not destination:
        raise ValueError(f"Could not locate target host in SSH string: {raw!r}")

    if "@" in destination:
        parsed_user, host_part = destination.rsplit("@", 1)
        if parsed_user:
            user = parsed_user
    else:
        host_part = destination

    if ":" in host_part and not host_part.startswith("["):
        h_only, p_only = host_part.rsplit(":", 1)
        if p_only.isdigit():
            host_part = h_only
            port = int(p_only)

    host_part = host_part.strip("[]").strip()
    if not host_part:
        raise ValueError(f"Invalid host in SSH string: {raw!r}")
    if not (1 <= port <= 65535):
        raise ValueError(f"SSH port out of range: {port}")

    return ParsedSshEndpoint(
        host=host_part,
        port=port,
        user=user or "root",
        identity_file=identity_file,
    )


def posix_quote(value: str) -> str:
    """Quote a string safely for remote POSIX bash execution."""
    return shlex.quote(value)


def profile_path_for(workspace: Path) -> Path:
    return workspace / PROFILE_FILENAME


def save_profile(workspace: Path, profile: RemoteProfile) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    out = profile_path_for(workspace)
    payload = asdict(profile)
    if not payload.get("created_at"):
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load_profile(workspace: Path) -> RemoteProfile:
    p = profile_path_for(workspace)
    if not p.exists():
        raise FileNotFoundError(
            f"Remote profile not found at {p}. Run `python scripts/remote_gpu.py init --workspace {workspace} ...` first."
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    return RemoteProfile(
        host=str(data["host"]),
        port=int(data.get("port", 22)),
        user=str(data.get("user", "root")),
        key_path=str(data.get("key_path", "")),
        remote_dir=str(data.get("remote_dir", "/root/researchflow_run")),
        created_at=str(data.get("created_at", "")),
    )


def base_ssh_args(profile: RemoteProfile, batch_mode: bool = True) -> list[str]:
    ssh_bin = shutil.which("ssh") or "ssh"
    args = [
        ssh_bin,
        "-p",
        str(profile.port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if batch_mode:
        args.extend(["-o", "BatchMode=yes"])
    if profile.key_path:
        args.extend(["-i", profile.key_path, "-o", "IdentitiesOnly=yes"])
    args.append(profile.target())
    return args


def default_ssh_runner(
    profile: RemoteProfile,
    remote_cmd: str,
    stdin_bytes: bytes | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[bytes]:
    cmd = base_ssh_args(profile, batch_mode=True) + [f"bash -lc {posix_quote(remote_cmd)}"]
    return subprocess.run(
        cmd,
        input=stdin_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def ensure_keypair(workspace: Path, explicit_key: str = "") -> tuple[Path, Path]:
    """Return `(private_key_path, public_key_path)`, generating an Ed25519 keypair if needed."""
    if explicit_key:
        priv = Path(explicit_key).expanduser().resolve()
        pub = Path(str(priv) + ".pub")
        if not priv.exists():
            raise FileNotFoundError(f"Specified SSH identity file does not exist: {priv}")
        return priv, pub

    ssh_dir = (workspace / ".ssh").resolve()
    ssh_dir.mkdir(parents=True, exist_ok=True)
    priv = ssh_dir / "id_ed25519"
    pub = ssh_dir / "id_ed25519.pub"
    if not priv.exists() or not pub.exists():
        keygen = shutil.which("ssh-keygen") or "ssh-keygen"
        res = subprocess.run(
            [keygen, "-t", "ed25519", "-N", "", "-C", f"researchflow-{workspace.name}", "-f", str(priv)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"ssh-keygen failed: {res.stderr.strip() or res.stdout.strip()}")
        try:
            os.chmod(priv, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return priv, pub


def bootstrap_authorized_key(
    profile: RemoteProfile,
    pubkey_text: str,
    password: str,
    timeout: int = 30,
) -> str:
    """Install `pubkey_text` on `profile` using `SSH_ASKPASS` first, then optional `paramiko` fallback."""
    clean_pub = pubkey_text.strip()
    if not clean_pub:
        raise ValueError("Empty public key content")

    install_script = (
        "umask 077 && mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
        f"grep -qxF {posix_quote(clean_pub)} ~/.ssh/authorized_keys || "
        f"printf '%s\\n' {posix_quote(clean_pub)} >> ~/.ssh/authorized_keys"
    )

    # Attempt 1: Native OpenSSH with SSH_ASKPASS + SSH_ASKPASS_REQUIRE=force (zero Python dependencies)
    askpass_err = ""
    with tempfile.TemporaryDirectory(prefix="rf_askpass_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = os.environ.copy()
        env["RF_BOOTSTRAP_SECRET"] = password
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["DISPLAY"] = env.get("DISPLAY") or "researchflow:0"

        if os.name == "nt":
            helper = tmp_path / "askpass.bat"
            py_exe = sys.executable
            py_helper = tmp_path / "emit_secret.py"
            py_helper.write_text(
                "import os, sys\nsys.stdout.write(os.environ.get('RF_BOOTSTRAP_SECRET', '') + '\\n')\n",
                encoding="utf-8",
            )
            helper.write_text(f'@"{py_exe}" "{py_helper}"\r\n', encoding="utf-8")
        else:
            helper = tmp_path / "askpass.sh"
            helper.write_text('#!/bin/sh\nprintf "%s\\n" "$RF_BOOTSTRAP_SECRET"\n', encoding="utf-8")
            helper.chmod(0o700)

        env["SSH_ASKPASS"] = str(helper)
        ssh_bin = shutil.which("ssh") or "ssh"
        cmd = [
            ssh_bin,
            "-p",
            str(profile.port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            profile.target(),
            f"bash -lc {posix_quote(install_script)}",
        ]
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
            check=False,
        )
        if res.returncode == 0:
            return "openssh-askpass"
        askpass_err = res.stderr.decode("utf-8", errors="replace").strip()

    # Attempt 2: Optional paramiko fallback if installed locally
    try:
        import paramiko  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            f"OpenSSH askpass bootstrap failed ({askpass_err}) and `paramiko` is not installed."
        ) from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=profile.host,
            port=profile.port,
            username=profile.user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
        )
        _, stdout, stderr = client.exec_command(f"bash -lc {posix_quote(install_script)}", timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            err_txt = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Paramiko key install failed (exit {exit_status}): {err_txt}")
        return "paramiko"
    finally:
        client.close()


def should_exclude(rel_posix: str, extra_excludes: tuple[str, ...] = ()) -> bool:
    parts = [p for p in rel_posix.split("/") if p and p != "."]
    patterns = DEFAULT_EXCLUDES + extra_excludes
    for part in parts:
        for pat in patterns:
            if fnmatch.fnmatch(part, pat):
                return True
    for pat in patterns:
        if "/" in pat and fnmatch.fnmatch(rel_posix, pat):
            return True
    return False


def build_tar_bytes(source: Path, extra_excludes: tuple[str, ...] = ()) -> tuple[bytes, list[str]]:
    """Pack `source` (directory or single file) into an in-memory `.tar.gz` byte buffer."""
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Local source path does not exist: {source}")

    included: list[str] = []
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        if source.is_file():
            tf.add(str(source), arcname=source.name, recursive=False)
            included.append(source.name)
        else:
            for root, dirs, files in os.walk(source):
                root_path = Path(root)
                rel_dir = root_path.relative_to(source).as_posix()
                kept_dirs = []
                for d in sorted(dirs):
                    cand = f"{rel_dir}/{d}" if rel_dir != "." else d
                    if not should_exclude(cand, extra_excludes):
                        kept_dirs.append(d)
                dirs[:] = kept_dirs

                for fn in sorted(files):
                    rel_file = f"{rel_dir}/{fn}" if rel_dir != "." else fn
                    if should_exclude(rel_file, extra_excludes):
                        continue
                    full_file = root_path / fn
                    tf.add(str(full_file), arcname=rel_file, recursive=False)
                    included.append(rel_file)
    return buf.getvalue(), included


def safe_extract_tar_bytes(tar_bytes: bytes, dest_dir: Path) -> list[str]:
    """Extract `.tar.gz` bytes into `dest_dir` while blocking `..` / absolute-path tar-slip attacks."""
    dest_resolved = dest_dir.resolve()
    dest_resolved.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            norm_name = PurePosixPath(member.name)
            if norm_name.is_absolute() or ".." in norm_name.parts:
                raise ValueError(f"Unsafe path in remote tar stream blocked: {member.name!r}")
            if member.issym() or member.islnk():
                link_target = PurePosixPath(member.linkname)
                if link_target.is_absolute() or ".." in link_target.parts:
                    raise ValueError(f"Unsafe symlink in remote tar stream blocked: {member.name!r} -> {member.linkname!r}")
            target_path = (dest_resolved / Path(*norm_name.parts)).resolve()
            if target_path != dest_resolved and dest_resolved not in target_path.parents:
                raise ValueError(f"Path traversal outside destination blocked: {member.name!r}")
            try:
                tf.extract(member, path=str(dest_resolved), filter="data")
            except TypeError:
                tf.extract(member, path=str(dest_resolved))
            if member.isfile():
                extracted.append(norm_name.as_posix())
    return extracted


def build_probe_script(remote_dir: str) -> str:
    q_dir = posix_quote(remote_dir)
    return f"""python3 - {q_dir} <<'PY'
import json, os, shutil, subprocess, sys

remote_dir = sys.argv[1]
os.makedirs(remote_dir, exist_ok=True)

def run_out(cmd):
    try:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""

gpus = []
raw_gpu = run_out("nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader,nounits")
for line in raw_gpu.splitlines():
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 7:
        gpus.append({{
            "index": int(parts[0]),
            "name": parts[1],
            "vram_total_mb": int(float(parts[2])),
            "vram_used_mb": int(float(parts[3])),
            "vram_free_mb": int(float(parts[4])),
            "gpu_util_pct": int(float(parts[5])),
            "temp_c": int(float(parts[6])),
        }})

gpu_procs = []
raw_procs = run_out("nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader,nounits")
for line in raw_procs.splitlines():
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 3:
        gpu_procs.append({{"pid": parts[0], "name": parts[1], "vram_mb": parts[2]}})

disks = {{}}
for mount in ["/", "/root/autodl-tmp", "/hy-tmp", "/data", remote_dir]:
    if os.path.exists(mount):
        usage = shutil.disk_usage(mount)
        disks[mount] = {{
            "total_gb": round(usage.total / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
        }}

mem_total_gb, mem_avail_gb = 0.0, 0.0
if os.path.exists("/proc/meminfo"):
    info = {{}}
    for ln in open("/proc/meminfo", encoding="utf-8", errors="ignore"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            nums = [int(x) for x in v.split() if x.isdigit()]
            if nums:
                info[k.strip()] = nums[0]
    mem_total_gb = round(info.get("MemTotal", 0) / (1024**2), 2)
    mem_avail_gb = round(info.get("MemAvailable", 0) / (1024**2), 2)

torch_info = {{"installed": False, "version": "", "cuda_available": False, "cuda_version": ""}}
try:
    import torch
    torch_info = {{
        "installed": True,
        "version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_version": str(torch.version.cuda or ""),
    }}
except Exception:
    pass

warnings = []
root_free = disks.get("/", {{}}).get("free_gb", 999.0)
if root_free < 15.0:
    warnings.append(f"Root disk '/' has only {{root_free}} GB free; keep HF_HOME/TORCH_HOME on a data mount.")

print(json.dumps({{
    "cpu_cores": os.cpu_count() or 1,
    "ram_total_gb": mem_total_gb,
    "ram_avail_gb": mem_avail_gb,
    "gpus": gpus,
    "gpu_processes": gpu_procs,
    "disks": disks,
    "python_version": sys.version.split()[0],
    "torch": torch_info,
    "has_py_spy": bool(shutil.which("py-spy")),
    "remote_dir": remote_dir,
    "warnings": warnings,
}}, ensure_ascii=False))
PY"""


def validate_job_id(job_id: str) -> str:
    cleaned = job_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", cleaned):
        raise ValueError(f"Invalid job_id {job_id!r}: use 1-64 chars of [A-Za-z0-9_.-]")
    return cleaned


def build_launch_script(
    remote_dir: str,
    job_id: str,
    command: str,
    workdir_rel: str = "",
    gpu_devices: str = "",
) -> str:
    job_id = validate_job_id(job_id)
    work_path = f"{remote_dir.rstrip('/')}/{workdir_rel.strip('/')}" if workdir_rel.strip("/") else remote_dir.rstrip("/")
    job_dir = f"{remote_dir.rstrip('/')}/.rf_jobs/{job_id}"
    cache_root = f"{remote_dir.rstrip('/')}/.cache"

    runner_lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        f"mkdir -p {posix_quote(cache_root)}/huggingface {posix_quote(cache_root)}/modelscope {posix_quote(cache_root)}/torch",
        f"export HF_HOME=\"${{HF_HOME:-{cache_root}/huggingface}}\"",
        f"export MODELSCOPE_CACHE=\"${{MODELSCOPE_CACHE:-{cache_root}/modelscope}}\"",
        f"export TORCH_HOME=\"${{TORCH_HOME:-{cache_root}/torch}}\"",
        "export PYTHONUNBUFFERED=1",
    ]
    if gpu_devices:
        runner_lines.append(f"export CUDA_VISIBLE_DEVICES={posix_quote(gpu_devices)}")
    runner_lines.extend(
        [
            f"cd {posix_quote(work_path)}",
            command,
            "rc=$?",
            f"printf '%s\\n' \"$rc\" > {posix_quote(job_dir + '/exit_code')}",
            f"date -u +\"%Y-%m-%dT%H:%M:%SZ\" > {posix_quote(job_dir + '/finished_at')}",
            "exit $rc",
        ]
    )
    runner_body = "\n".join(runner_lines) + "\n"

    return f"""set -euo pipefail
mkdir -p {posix_quote(job_dir)} {posix_quote(work_path)}
rm -f {posix_quote(job_dir + '/exit_code')} {posix_quote(job_dir + '/finished_at')}
cat > {posix_quote(job_dir + '/runner.sh')} <<'RF_RUNNER_EOF'
{runner_body}RF_RUNNER_EOF
chmod +x {posix_quote(job_dir + '/runner.sh')}
date -u +"%Y-%m-%dT%H:%M:%SZ" > {posix_quote(job_dir + '/started_at')}
nohup setsid bash {posix_quote(job_dir + '/runner.sh')} > {posix_quote(job_dir + '/stdout.log')} 2>&1 < /dev/null &
pid=$!
printf '%s\\n' "$pid" > {posix_quote(job_dir + '/pid')}
python3 - <<PY
import json
meta = {{
    "job_id": {json.dumps(job_id)},
    "pid": int("$pid"),
    "workdir": {json.dumps(work_path)},
    "command": {json.dumps(command)},
    "log_path": {json.dumps(job_dir + '/stdout.log')},
}}
open({json.dumps(job_dir + '/meta.json')}, "w", encoding="utf-8").write(json.dumps(meta, indent=2) + "\\n")
print(json.dumps(meta))
PY"""


def detect_log_anomalies(log_text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in FATAL_LOG_PATTERNS:
        if pattern.search(log_text):
            found.append(label)
    return found


def build_status_script(
    remote_dir: str,
    job_id: str,
    progress_rel: str = "",
    tail_lines: int = 40,
) -> str:
    job_id = validate_job_id(job_id)
    job_dir = f"{remote_dir.rstrip('/')}/.rf_jobs/{job_id}"
    prog_path = f"{remote_dir.rstrip('/')}/{progress_rel.lstrip('/')}" if progress_rel else ""
    return f"""python3 - {posix_quote(job_dir)} {posix_quote(prog_path)} {int(tail_lines)} <<'PY'
import json, os, subprocess, sys

job_dir, prog_path, tail_n = sys.argv[1], sys.argv[2], int(sys.argv[3])
result = {{
    "exists": os.path.isdir(job_dir),
    "state": "NOT_FOUND",
    "pid": None,
    "alive": False,
    "exit_code": None,
    "started_at": "",
    "finished_at": "",
    "gpus": [],
    "log_tail": "",
    "log_bytes": 0,
    "progress": None,
}}

if os.path.isdir(job_dir):
    def read_txt(name):
        p = os.path.join(job_dir, name)
        return open(p, encoding="utf-8", errors="replace").read().strip() if os.path.exists(p) else ""

    pid_str = read_txt("pid")
    if pid_str.isdigit():
        result["pid"] = int(pid_str)
        result["alive"] = os.path.exists(f"/proc/{{pid_str}}")
    ec_str = read_txt("exit_code")
    if ec_str.lstrip("-").isdigit():
        result["exit_code"] = int(ec_str)
    result["started_at"] = read_txt("started_at")
    result["finished_at"] = read_txt("finished_at")

    if result["alive"]:
        result["state"] = "RUNNING"
    elif result["exit_code"] is not None:
        result["state"] = "COMPLETED" if result["exit_code"] == 0 else "FAILED"
    else:
        result["state"] = "TERMINATED_WITHOUT_EXIT_CODE"

    log_p = os.path.join(job_dir, "stdout.log")
    if os.path.exists(log_p):
        result["log_bytes"] = os.path.getsize(log_p)
        with open(log_p, "rb") as f:
            f.seek(max(0, result["log_bytes"] - 32768))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
            result["log_tail"] = "\\n".join(lines[-tail_n:]) if tail_n > 0 else ""

try:
    r = subprocess.run(
        "nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8
    )
    if r.returncode == 0:
        for ln in r.stdout.strip().splitlines():
            ps = [x.strip() for x in ln.split(",")]
            if len(ps) >= 4:
                result["gpus"].append({{
                    "index": int(ps[0]),
                    "gpu_util_pct": int(float(ps[1])),
                    "vram_used_mb": int(float(ps[2])),
                    "vram_total_mb": int(float(ps[3])),
                }})
except Exception:
    pass

if prog_path and os.path.exists(prog_path):
    try:
        result["progress"] = json.loads(open(prog_path, encoding="utf-8").read())
    except Exception as e:
        result["progress"] = {{"_parse_error": str(e)}}

print(json.dumps(result, ensure_ascii=False))
PY"""


def enrich_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    anomalies = detect_log_anomalies(str(payload.get("log_tail") or ""))
    gpus = payload.get("gpus") or []
    if payload.get("state") == "RUNNING" and gpus:
        max_util = max(int(g.get("gpu_util_pct", 0)) for g in gpus)
        if max_util < 5:
            anomalies.append("LOW_GPU_UTIL_POSSIBLE_CPU_BOTTLENECK_OR_HANG")
    payload["anomalies"] = anomalies
    return payload


def run_checked(
    profile: RemoteProfile,
    remote_cmd: str,
    runner: SshRunner = default_ssh_runner,
    stdin_bytes: bytes | None = None,
    timeout: int = 60,
) -> str:
    res = runner(profile, remote_cmd, stdin_bytes, timeout)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace").strip()
        out = res.stdout.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Remote SSH command failed (exit {res.returncode}): {err or out}")
    return res.stdout.decode("utf-8", errors="replace")


def cmd_init(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    if args.ssh:
        ep = parse_ssh_command(args.ssh)
        host = args.host or ep.host
        port = args.port or ep.port
        user = args.user or ep.user
        explicit_key = args.identity or ep.identity_file
    else:
        if not args.host:
            raise ValueError("Provide either `--ssh \"ssh -p PORT user@host\"` or `--host HOST`.")
        host = args.host
        port = args.port or 22
        user = args.user or "root"
        explicit_key = args.identity or ""

    priv_key, pub_key = ensure_keypair(workspace, explicit_key=explicit_key)
    remote_dir = args.remote_dir or f"/root/autodl-tmp/rf_{workspace.name}"

    profile = RemoteProfile(
        host=host,
        port=int(port),
        user=user,
        key_path=str(priv_key),
        remote_dir=remote_dir,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    password = ""
    if args.password_stdin:
        password = sys.stdin.read().rstrip("\r\n")
    elif args.password_env:
        password = os.environ.get(args.password_env, "")
    elif args.password:
        password = args.password

    auth_method = "existing-key"
    if password:
        if not pub_key.exists():
            raise FileNotFoundError(f"Public key missing for bootstrap: {pub_key}")
        auth_method = bootstrap_authorized_key(profile, pub_key.read_text(encoding="utf-8"), password)

    # Verify passwordless SSH works and resolve optimal remote_dir if /root/autodl-tmp doesn't exist
    verify_cmd = (
        "if [ ! -d /root/autodl-tmp ] && [ "
        + posix_quote(remote_dir)
        + " = "
        + posix_quote(f"/root/autodl-tmp/rf_{workspace.name}")
        + " ]; then echo /root/rf_"
        + workspace.name
        + "; else echo "
        + posix_quote(remote_dir)
        + "; fi"
    )
    resolved_dir = run_checked(profile, verify_cmd, runner=runner, timeout=20).strip().splitlines()[-1]
    profile.remote_dir = resolved_dir
    run_checked(profile, f"mkdir -p {posix_quote(profile.remote_dir)}", runner=runner, timeout=20)
    saved_to = save_profile(workspace, profile)
    return {
        "status": "ok",
        "auth_method": auth_method,
        "profile_path": str(saved_to),
        "host": profile.host,
        "port": profile.port,
        "user": profile.user,
        "remote_dir": profile.remote_dir,
    }


def cmd_probe(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    profile = load_profile(Path(args.workspace).resolve())
    raw = run_checked(profile, build_probe_script(profile.remote_dir), runner=runner, timeout=30)
    return json.loads(raw.strip().splitlines()[-1])


def cmd_push(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    profile = load_profile(workspace)
    src = (workspace / args.src).resolve() if not Path(args.src).is_absolute() else Path(args.src).resolve()
    dest_rel = (args.dest or args.src).strip("/")
    remote_dest = f"{profile.remote_dir.rstrip('/')}/{dest_rel}" if dest_rel and dest_rel != "." else profile.remote_dir.rstrip("/")

    tar_bytes, files = build_tar_bytes(src, extra_excludes=tuple(args.exclude or ()))
    if src.is_file():
        remote_parent = str(PurePosixPath(remote_dest).parent)
        extract_cmd = f"mkdir -p {posix_quote(remote_parent)} && tar -xzf - -C {posix_quote(remote_parent)}"
    else:
        extract_cmd = f"mkdir -p {posix_quote(remote_dest)} && tar -xzf - -C {posix_quote(remote_dest)}"

    run_checked(profile, extract_cmd, runner=runner, stdin_bytes=tar_bytes, timeout=180)
    return {
        "status": "ok",
        "files_pushed": len(files),
        "archive_bytes": len(tar_bytes),
        "remote_dest": remote_dest,
    }


def cmd_pull(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    profile = load_profile(workspace)
    src_rel = args.src.strip("/")
    remote_src = f"{profile.remote_dir.rstrip('/')}/{src_rel}" if src_rel else profile.remote_dir.rstrip("/")
    local_dest = (workspace / (args.dest or args.src)).resolve()

    remote_pack = (
        f"if [ -d {posix_quote(remote_src)} ]; then "
        f"tar -czf - -C {posix_quote(remote_src)} .; "
        f"elif [ -f {posix_quote(remote_src)} ]; then "
        f"tar -czf - -C \"$(dirname {posix_quote(remote_src)})\" \"$(basename {posix_quote(remote_src)})\"; "
        f"else echo 'Remote path missing' >&2; exit 2; fi"
    )
    res = runner(profile, remote_pack, None, 180)
    if res.returncode != 0:
        raise RuntimeError(f"Remote pull failed: {res.stderr.decode('utf-8', errors='replace').strip()}")

    target_dir = local_dest.parent if local_dest.suffix else local_dest
    extracted = safe_extract_tar_bytes(res.stdout, target_dir)
    return {
        "status": "ok",
        "files_pulled": len(extracted),
        "local_dest": str(target_dir),
    }


def cmd_launch(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    profile = load_profile(Path(args.workspace).resolve())
    script = build_launch_script(
        remote_dir=profile.remote_dir,
        job_id=args.job_id,
        command=args.cmd,
        workdir_rel=args.workdir or "",
        gpu_devices=args.gpu or "",
    )
    raw = run_checked(profile, script, runner=runner, timeout=30)
    return json.loads(raw.strip().splitlines()[-1])


def cmd_status(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    profile = load_profile(Path(args.workspace).resolve())
    script = build_status_script(
        remote_dir=profile.remote_dir,
        job_id=args.job_id,
        progress_rel=args.progress_file or "",
        tail_lines=args.tail,
    )
    raw = run_checked(profile, script, runner=runner, timeout=30)
    payload = json.loads(raw.strip().splitlines()[-1])
    return enrich_status_payload(payload)


def cmd_profile(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    profile = load_profile(Path(args.workspace).resolve())
    job_id = validate_job_id(args.job_id)
    job_dir = f"{profile.remote_dir.rstrip('/')}/.rf_jobs/{job_id}"
    prof_cmd = f"""pid=$(cat {posix_quote(job_dir + '/pid')} 2>/dev/null || true)
if [ -z "$pid" ] || [ ! -d "/proc/$pid" ]; then
  echo "Process for job {job_id} is not running"; exit 1
fi
if command -v py-spy >/dev/null 2>&1; then
  py-spy dump --pid "$pid"
else
  echo "=== /proc/$pid/stat ===" && cat "/proc/$pid/stat" || true
  echo "=== /proc/$pid/wchan ===" && cat "/proc/$pid/wchan" && echo "" || true
  ps -o pid,ppid,pcpu,pmem,etime,stat,cmd --ppid "$pid" -p "$pid" || true
fi"""
    out = run_checked(profile, prof_cmd, runner=runner, timeout=30)
    return {"job_id": job_id, "snapshot": out.strip()}


def cmd_kill(args: argparse.Namespace, runner: SshRunner = default_ssh_runner) -> dict[str, Any]:
    profile = load_profile(Path(args.workspace).resolve())
    job_id = validate_job_id(args.job_id)
    job_dir = f"{profile.remote_dir.rstrip('/')}/.rf_jobs/{job_id}"
    kill_cmd = f"""pid=$(cat {posix_quote(job_dir + '/pid')} 2>/dev/null || true)
if [ -z "$pid" ]; then echo "NO_PID"; exit 0; fi
if [ -d "/proc/$pid" ]; then
  kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  sleep 2
  if [ -d "/proc/$pid" ]; then
    kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  echo "KILLED:$pid"
else
  echo "ALREADY_EXITED:$pid"
fi"""
    out = run_checked(profile, kill_cmd, runner=runner, timeout=20).strip()
    return {"job_id": job_id, "result": out}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ResearchFlow zero-dependency remote GPU helper CLI.")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_init = sub.add_parser("init", help="Bootstrap SSH key auth and save workspace remote host profile.")
    p_init.add_argument("--workspace", required=True, help="Path to `workspaces/<project>`.")
    p_init.add_argument("--ssh", default="", help="Full SSH string, e.g. `ssh -p 51263 root@host`.")
    p_init.add_argument("--host", default="", help="Remote hostname or IP.")
    p_init.add_argument("--port", type=int, default=0, help="Remote SSH port.")
    p_init.add_argument("--user", default="", help="Remote SSH user (default: root).")
    p_init.add_argument("--identity", default="", help="Existing local private key path.")
    p_init.add_argument("--remote-dir", default="", help="Remote workspace directory.")
    p_init.add_argument("--password", default="", help="One-time password for SSH key bootstrap.")
    p_init.add_argument("--password-env", default="", help="Env var holding one-time SSH password.")
    p_init.add_argument("--password-stdin", action="store_true", help="Read one-time SSH password from stdin.")

    p_probe = sub.add_parser("probe", help="Inspect remote GPUs, VRAM, disks, RAM, and PyTorch/CUDA.")
    p_probe.add_argument("--workspace", required=True)

    p_push = sub.add_parser("push", help="Sync local directory/file to remote workspace via tar-over-SSH.")
    p_push.add_argument("--workspace", required=True)
    p_push.add_argument("--src", required=True, help="Path relative to workspace (or absolute path).")
    p_push.add_argument("--dest", default="", help="Relative destination under remote_dir (defaults to --src).")
    p_push.add_argument("--exclude", action="append", default=[], help="Additional glob pattern to exclude.")

    p_pull = sub.add_parser("pull", help="Pull remote results/logs back into local workspace.")
    p_pull.add_argument("--workspace", required=True)
    p_pull.add_argument("--src", required=True, help="Relative path under remote_dir to download.")
    p_pull.add_argument("--dest", default="", help="Relative destination inside local workspace.")

    p_launch = sub.add_parser("launch", help="Start a detached daemon job with exit-code tracking.")
    p_launch.add_argument("--workspace", required=True)
    p_launch.add_argument("--job-id", required=True, help="Short job identifier, e.g. `gate0` or `main_b1`.")
    p_launch.add_argument("--cmd", required=True, help="Command line to execute remotely.")
    p_launch.add_argument("--workdir", default="", help="Relative subdirectory under remote_dir.")
    p_launch.add_argument("--gpu", default="", help="Optional CUDA_VISIBLE_DEVICES value, e.g. `0` or `0,1`.")

    p_status = sub.add_parser("status", help="Single-shot job state, GPU utilization, log tail, and anomaly scan.")
    p_status.add_argument("--workspace", required=True)
    p_status.add_argument("--job-id", required=True)
    p_status.add_argument("--progress-file", default="", help="Optional relative JSON status file to read.")
    p_status.add_argument("--tail", type=int, default=40, help="Number of tail log lines to return.")

    p_prof = sub.add_parser("profile", help="Dump live Python stack or process state of a running job.")
    p_prof.add_argument("--workspace", required=True)
    p_prof.add_argument("--job-id", required=True)

    p_kill = sub.add_parser("kill", help="Terminate a detached remote job's entire process group.")
    p_kill.add_argument("--workspace", required=True)
    p_kill.add_argument("--job-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "init": cmd_init,
        "probe": cmd_probe,
        "push": cmd_push,
        "pull": cmd_pull,
        "launch": cmd_launch,
        "status": cmd_status,
        "profile": cmd_profile,
        "kill": cmd_kill,
    }
    try:
        out = dispatch[args.subcommand](args)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
