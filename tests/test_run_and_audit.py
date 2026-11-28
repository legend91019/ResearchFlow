from __future__ import annotations

import json
from pathlib import Path
import struct
import sys

import pytest

from scripts import audit_exp, run_matrix


def _make_valid_png(path: Path, width: int = 640, height: int = 400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr_data + b"\x00" * 300
    path.write_bytes(header)


def _make_valid_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n" + b"0" * 320 + b"\n%%EOF\n")


def test_run_matrix_idempotent_resume_and_invalidation(tmp_path: Path) -> None:
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    eval_py = exp_dir / "eval_harness.py"
    eval_py.write_text("SCORE_SCALE = 1.0\n", encoding="utf-8")
    eval_sha = run_matrix.sha256_file(eval_py)

    worker_py = exp_dir / "toy_run.py"
    worker_py.write_text(
        "import json, pathlib, sys\n"
        "cid, val, out = sys.argv[1], float(sys.argv[2]), pathlib.Path(sys.argv[3])\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_text(json.dumps({'cid': cid, 'acc': val}), encoding='utf-8')\n",
        encoding="utf-8",
    )

    py_bin = f'"{sys.executable}"'
    manifest = {
        "evaluator_path": "eval_harness.py",
        "evaluator_sha256": eval_sha,
        "runs": [
            {
                "condition_id": "base_s42",
                "method": "baseline",
                "benchmark": "cl4",
                "seed": 42,
                "tier": "main",
                "command": f"{py_bin} toy_run.py base_s42 75.20 results/base_s42.json",
                "metrics_file": "results/base_s42.json",
            },
            {
                "condition_id": "ours_s42",
                "method": "ours",
                "benchmark": "cl4",
                "seed": 42,
                "tier": "main",
                "command": f"{py_bin} toy_run.py ours_s42 78.46 results/ours_s42.json",
                "metrics_file": "results/ours_s42.json",
            },
        ],
    }
    manifest_path = exp_dir / "exp_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ledger_path = exp_dir / "results" / "ledger.jsonl"

    parser = run_matrix.build_parser()
    # First run on commit_v1: execute only base_s42
    res1 = run_matrix.cmd_run(
        parser.parse_args(
            [
                "run",
                "--manifest",
                str(manifest_path),
                "--ledger",
                str(ledger_path),
                "--only",
                "base_s42",
                "--commit",
                "commit_v1",
            ]
        )
    )
    assert res1["completed_now"] == 1

    # Coverage audit should fail right now because ours_s42 is still pending
    rep_incomplete = audit_exp.run_audit(manifest_path, ledger_path, exp_dir)
    assert not rep_incomplete.passed
    assert rep_incomplete.pending_count == 1

    # Second run on commit_v2: skips base_s42, executes ours_s42 -> triggers mixed-commit error!
    res2 = run_matrix.cmd_run(
        parser.parse_args(
            [
                "run",
                "--manifest",
                str(manifest_path),
                "--ledger",
                str(ledger_path),
                "--workers",
                "2",
                "--commit",
                "commit_v2",
            ]
        )
    )
    assert res2["skipped_completed"] == 1
    assert res2["completed_now"] == 1

    rep_mixed = audit_exp.run_audit(manifest_path, ledger_path, exp_dir)
    assert not rep_mixed.passed
    assert any("mix multiple git commits" in e for e in rep_mixed.errors)

    # Invalidate base_s42 (append-only) and re-run on commit_v2 -> clean single-commit audit PASS!
    inv = run_matrix.cmd_invalidate(
        parser.parse_args(
            [
                "invalidate",
                "--ledger",
                str(ledger_path),
                "--pattern",
                "^base_",
                "--reason",
                "Shared tokenizer bugfix in commit_v2",
            ]
        )
    )
    assert inv["invalidated_count"] == 1

    res3 = run_matrix.cmd_run(
        parser.parse_args(
            [
                "run",
                "--manifest",
                str(manifest_path),
                "--ledger",
                str(ledger_path),
                "--commit",
                "commit_v2",
            ]
        )
    )
    assert res3["executed"] == 1
    assert res3["completed_now"] == 1

    rep_clean = audit_exp.run_audit(manifest_path, ledger_path, exp_dir)
    assert rep_clean.passed
    assert rep_clean.commits_seen == ["commit_v2"]


def test_evaluator_tampering_blocks_execution(tmp_path: Path) -> None:
    eval_py = tmp_path / "eval_harness.py"
    eval_py.write_text("x = 1\n", encoding="utf-8")
    orig_sha = run_matrix.sha256_file(eval_py)
    eval_py.write_text("x = 999  # tampered!\n", encoding="utf-8")

    manifest_path = tmp_path / "exp_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "evaluator_path": "eval_harness.py",
                "evaluator_sha256": orig_sha,
                "runs": [{"condition_id": "c1", "command": "echo hi"}],
            }
        ),
        encoding="utf-8",
    )
    parser = run_matrix.build_parser()
    with pytest.raises(RuntimeError, match="Evaluator SHA-256 mismatch"):
        run_matrix.cmd_run(parser.parse_args(["run", "--manifest", str(manifest_path)]))


def test_audit_identical_metrics_warning_plot_ast_and_evidence(tmp_path: Path) -> None:
    exp_dir = tmp_path / "exp"
    plots_dir = exp_dir / "plots"
    figs_dir = exp_dir / "figures"
    res_dir = exp_dir / "results"
    plots_dir.mkdir(parents=True)
    res_dir.mkdir(parents=True)

    _make_valid_pdf(figs_dir / "fig_e1.pdf")
    _make_valid_png(figs_dir / "fig_e1.png")

    # Good plot script that loads JSON from disk
    (plots_dir / "plot_good.py").write_text(
        "import json, pathlib\n"
        "data = json.loads(pathlib.Path('results/summary.json').read_text())\n",
        encoding="utf-8",
    )
    (res_dir / "summary.json").write_text(json.dumps({"ours": {"aa": 78.46}}), encoding="utf-8")

    manifest_path = exp_dir / "exp_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "expected_figures": ["figures/fig_e1.pdf", "figures/fig_e1.png"],
                "runs": [
                    {"condition_id": "ours_full", "benchmark": "b1", "seed": 42, "command": "true"},
                    {"condition_id": "ours_ablation", "benchmark": "b1", "seed": 42, "command": "true"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger_path = res_dir / "ledger.jsonl"
    ledger_lines = [
        {"condition_id": "ours_full", "status": "completed", "git_commit": "abc", "metrics": {"aa": 78.46, "bwt": -0.37}},
        {"condition_id": "ours_ablation", "status": "completed", "git_commit": "abc", "metrics": {"aa": 78.46, "bwt": -0.37}},
    ]
    ledger_path.write_text("\n".join(json.dumps(x) for x in ledger_lines) + "\n", encoding="utf-8")

    results_md = exp_dir / "07_exp_results.md"
    results_md.write_text("Main AA: 78.46% <!-- @evidence:results/summary.json#ours.aa -->\n", encoding="utf-8")

    rep = audit_exp.run_audit(manifest_path, ledger_path, exp_dir, plots_dir, figs_dir, results_md)
    assert rep.passed
    assert rep.checked_evidence_tags == 1
    assert any("INVESTIGATE_IDENTICAL_METRICS" in w for w in rep.warnings)

    # Inject bad hardcoded plot script -> audit must fail!
    (plots_dir / "plot_cheating.py").write_text(
        "scores = [71.2, 74.5, 76.8, 79.9]\nprint(scores)\n",
        encoding="utf-8",
    )
    rep_bad = audit_exp.run_audit(manifest_path, ledger_path, exp_dir, plots_dir, figs_dir, results_md)
    assert not rep_bad.passed
    assert any("plot_cheating.py" in e for e in rep_bad.errors)
