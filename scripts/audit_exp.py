#!/usr/bin/env python3
"""Deterministic post-execution coverage, provenance, integrity, and plotting audit CLI.

Audits an experiment directory before accepting `07_exp_results.md`:
1. Coverage Audit    : Cross-checks `exp_manifest.json` planned runs against `ledger.jsonl`
                       (flags missing/pending/failed/invalidated runs so nothing is silently dropped).
2. Provenance Audit  : Verifies `evaluator_sha256` immutability and checks whether valid `completed`
                       runs mix incompatible `git_commit` versions without explicit `compatible_commits`.
3. Integrity Audit   : Rejects `NaN`/`Inf` metric values and missing `metrics_file` outputs.
4. Mechanism Warning : Emits an `INVESTIGATE` warning (not a blind failure) when two distinct methods
                       or ablations on the same `(benchmark, seed)` produce identical metric vectors.
5. Plotting & Table  : AST-scans `plots/*.py` to catch hardcoded float arrays without data-file reads,
   Rendering Audit     verifies declared output figures (`.pdf`/`.png` headers & dimensions), and
                       optionally checks `@evidence[[path#key]]` tags in `07_exp_results.md`.

Zero third-party dependencies required (Python 3.10+ standard library only).
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
import struct
import sys
from typing import Any

try:
    from scripts.run_matrix import load_ledger_records, load_manifest, resolve_effective_states, sha256_file
except ModuleNotFoundError:
    from run_matrix import load_ledger_records, load_manifest, resolve_effective_states, sha256_file  # type: ignore[no-redef]

EVIDENCE_TAG_RE = re.compile(r"([+-]?\d+\.\d+)\s*(?:%|)\s*<!--\s*@evidence:([^#>]+)#([A-Za-z0-9_.-]+)\s*-->")


@dataclass
class AuditReport:
    passed: bool
    total_planned: int = 0
    completed_count: int = 0
    failed_count: int = 0
    invalidated_count: int = 0
    pending_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    commits_seen: list[str] = field(default_factory=list)
    checked_plots: int = 0
    checked_figures: int = 0
    checked_evidence_tags: int = 0


def _contains_nonfinite(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, dict):
        return any(_contains_nonfinite(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_nonfinite(v) for v in obj)
    return False


def _numeric_signature(metrics: dict[str, Any]) -> tuple[tuple[str, float], ...]:
    pairs: list[tuple[str, float]] = []
    for k, v in sorted(metrics.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            pairs.append((k, round(float(v), 6)))
    return tuple(pairs)


def scan_plot_script_ast(py_path: Path) -> list[str]:
    """Check whether a plotting script hardcodes >=4 float literals without reading any external data file."""
    src = py_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as exc:
        return [f"SyntaxError in plot script {py_path.name}: {exc}"]

    data_load_names = {
        "load",
        "loads",
        "read_text",
        "read_bytes",
        "open",
        "read_csv",
        "read_json",
        "read_parquet",
        "loadtxt",
        "genfromtxt",
    }
    has_data_read = False
    list_float_literals = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = ""
            if isinstance(node.func, ast.Name):
                fn_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fn_name = node.func.attr
            if fn_name in data_load_names:
                has_data_read = True
        elif isinstance(node, (ast.List, ast.Tuple)):
            floats_in_seq = [
                elt
                for elt in node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, float)
            ]
            if len(floats_in_seq) >= 3:
                list_float_literals += len(floats_in_seq)

    issues: list[str] = []
    if not has_data_read:
        issues.append(f"Plot script `{py_path.name}` does not read any external JSON/CSV/NPZ data file.")
    if list_float_literals >= 4 and not has_data_read:
        issues.append(
            f"Plot script `{py_path.name}` contains {list_float_literals} hardcoded float literals in sequences without loading results from disk."
        )
    return issues


def check_figure_binary(fig_path: Path) -> list[str]:
    if not fig_path.is_file():
        return [f"Missing figure file: {fig_path}"]
    size = fig_path.stat().st_size
    if size < 256:
        return [f"Figure file {fig_path.name} is suspiciously tiny ({size} bytes)."]

    head = fig_path.read_bytes()[:32]
    suffix = fig_path.suffix.lower()
    if suffix == ".pdf" and not head.startswith(b"%PDF-"):
        return [f"Figure file {fig_path.name} does not have a valid %PDF- header."]
    if suffix == ".png":
        if not head.startswith(b"\x89PNG\r\n\x1a\n"):
            return [f"Figure file {fig_path.name} does not have a valid PNG header."]
        if len(head) >= 24 and head[12:16] == b"IHDR":
            width, height = struct.unpack(">II", head[16:24])
            if width < 200 or height < 120:
                return [f"PNG {fig_path.name} resolution too small ({width}x{height}px)."]
    return []


def resolve_json_keypath(data: Any, keypath: str) -> float:
    cur = data
    for part in keypath.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise KeyError(f"Key segment {part!r} not found in path {keypath!r}")
    if not isinstance(cur, (int, float)) or isinstance(cur, bool):
        raise ValueError(f"Resolved value at {keypath!r} is not numeric: {cur!r}")
    return float(cur)


def verify_markdown_evidence_tags(md_path: Path, base_dir: Path) -> tuple[int, list[str]]:
    text = md_path.read_text(encoding="utf-8")
    errors: list[str] = []
    checked = 0
    cache: dict[Path, Any] = {}

    for match in EVIDENCE_TAG_RE.finditer(text):
        checked += 1
        shown_val = float(match.group(1))
        rel_file = match.group(2).strip()
        keypath = match.group(3).strip()
        target = (base_dir / rel_file).resolve()
        if not target.is_file():
            errors.append(f"@evidence file missing: {rel_file} (referenced in {md_path.name})")
            continue
        if target not in cache:
            cache[target] = json.loads(target.read_text(encoding="utf-8"))
        try:
            raw_val = resolve_json_keypath(cache[target], keypath)
        except Exception as exc:
            errors.append(f"@evidence key resolution failed for {rel_file}#{keypath}: {exc}")
            continue

        # Support both direct match (e.g. 78.46 vs 78.458) and fraction-to-percent (0.7846 vs 78.46)
        diff_direct = abs(shown_val - raw_val)
        diff_pct = abs(shown_val - raw_val * 100.0)
        if min(diff_direct, diff_pct) > 0.06:
            errors.append(
                f"@evidence numeric mismatch for {rel_file}#{keypath}: report shows {shown_val}, raw value is {raw_val}"
            )
    return checked, errors


def run_audit(
    manifest_path: Path,
    ledger_path: Path,
    base_dir: Path,
    plots_dir: Path | None = None,
    figures_dir: Path | None = None,
    results_md: Path | None = None,
) -> AuditReport:
    report = AuditReport(passed=True)
    manifest = load_manifest(manifest_path)
    records = load_ledger_records(ledger_path)
    states = resolve_effective_states(records)
    report.total_planned = len(manifest["runs"])

    # 1. Evaluator SHA-256 provenance lock
    eval_rel = str(manifest.get("evaluator_path", "")).strip()
    expected_eval_sha = str(manifest.get("evaluator_sha256", "")).strip()
    if eval_rel:
        eval_file = (base_dir / eval_rel).resolve()
        if not eval_file.is_file():
            report.errors.append(f"Evaluator script missing: {eval_rel}")
        elif expected_eval_sha:
            actual_sha = sha256_file(eval_file)
            if actual_sha.lower() != expected_eval_sha.lower():
                report.errors.append(
                    f"Evaluator SHA-256 tampered ({eval_rel}): expected {expected_eval_sha}, got {actual_sha}"
                )

    # 2. Coverage, version compatibility, and metric integrity
    commits_used: set[str] = set()
    sig_buckets: dict[tuple[str, str], list[str]] = {}

    for item in manifest["runs"]:
        cid = str(item["condition_id"]).strip()
        st = states.get(cid)
        if not st:
            report.pending_count += 1
            report.errors.append(f"Missing/unexecuted planned condition: {cid}")
            continue

        status = str(st.get("status", ""))
        if status == "completed":
            report.completed_count += 1
            c_sha = str(st.get("git_commit", "")).strip()
            if c_sha and c_sha != "unversioned":
                commits_used.add(c_sha)

            metrics = st.get("metrics")
            if isinstance(metrics, dict):
                if _contains_nonfinite(metrics):
                    report.errors.append(f"Non-finite (NaN/Inf) metric detected in completed run: {cid}")
                sig = _numeric_signature(metrics)
                if sig:
                    bench_seed = f"{item.get('benchmark', '')}::seed={item.get('seed', '')}"
                    sig_buckets.setdefault((bench_seed, str(sig)), []).append(cid)
            elif item.get("metrics_file"):
                report.errors.append(f"Completed run {cid} has empty/unparsed metrics payload.")
        elif status == "failed":
            report.failed_count += 1
            report.errors.append(f"Planned condition failed and remains unresolved: {cid}")
        elif status == "invalidated":
            report.invalidated_count += 1
            report.errors.append(f"Planned condition was invalidated and has not been re-run: {cid}")
        else:
            report.pending_count += 1
            report.errors.append(f"Planned condition in non-terminal state ({status}): {cid}")

    report.commits_seen = sorted(commits_used)
    compatible = {str(x).strip() for x in (manifest.get("compatible_commits") or []) if str(x).strip()}
    if len(commits_used) > 1 and not commits_used.issubset(compatible):
        report.errors.append(
            f"Completed runs mix multiple git commits {sorted(commits_used)} not listed in manifest `compatible_commits`."
        )

    # 3. Identical-metric investigation warning (never blind error—identical ablations can be real findings)
    for (bench_seed, _), cids in sorted(sig_buckets.items()):
        if len(cids) >= 2:
            report.warnings.append(
                f"INVESTIGATE_IDENTICAL_METRICS on ({bench_seed}): conditions {cids} produced identical numeric metrics. "
                "Verify whether an ablation flag is unwired or the mechanism genuinely had zero effect."
            )

    # 4. Plot scripts AST anti-hardcoding check
    if plots_dir and plots_dir.is_dir():
        for py_file in sorted(plots_dir.glob("*.py")):
            report.checked_plots += 1
            for err in scan_plot_script_ast(py_file):
                report.errors.append(err)

    # 5. Expected figure binary header & dimension check
    expected_figs = manifest.get("expected_figures") or []
    for fig_rel in expected_figs:
        fig_path = (base_dir / str(fig_rel)).resolve()
        report.checked_figures += 1
        report.errors.extend(check_figure_binary(fig_path))
    if figures_dir and figures_dir.is_dir() and not expected_figs:
        for fig_path in sorted(list(figures_dir.glob("*.pdf")) + list(figures_dir.glob("*.png"))):
            report.checked_figures += 1
            report.errors.extend(check_figure_binary(fig_path))

    # 6. Markdown `@evidence` numeric grounding check
    if results_md and results_md.is_file():
        cnt, ev_errs = verify_markdown_evidence_tags(results_md, base_dir)
        report.checked_evidence_tags = cnt
        report.errors.extend(ev_errs)

    report.passed = len(report.errors) == 0
    return report


def format_markdown_report(rep: AuditReport) -> str:
    verdict = "PASS" if rep.passed else "FAIL"
    lines = [
        f"# Experiment Audit Report — `{verdict}`",
        "",
        f"- **Planned Conditions**: `{rep.total_planned}`",
        f"- **Completed (Valid)**: `{rep.completed_count}` | **Failed**: `{rep.failed_count}` | **Invalidated**: `{rep.invalidated_count}` | **Pending**: `{rep.pending_count}`",
        f"- **Git Commits in Valid Runs**: `{', '.join(rep.commits_seen) if rep.commits_seen else 'unversioned'}`",
        f"- **Checked Plot Scripts**: `{rep.checked_plots}` | **Checked Figures**: `{rep.checked_figures}` | **Checked `@evidence` Tags**: `{rep.checked_evidence_tags}`",
        "",
    ]
    if rep.errors:
        lines.append("## Blocking Errors")
        for e in rep.errors:
            lines.append(f"- [ERROR] {e}")
        lines.append("")
    if rep.warnings:
        lines.append("## Investigation Warnings")
        for w in rep.warnings:
            lines.append(f"- [WARN] {w}")
        lines.append("")
    if not rep.errors and not rep.warnings:
        lines.append("All coverage, provenance, integrity, and rendering checks passed cleanly.")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ResearchFlow deterministic post-experiment auditor.")
    p.add_argument("--manifest", required=True, help="Path to `exp_manifest.json`.")
    p.add_argument("--ledger", default="results/ledger.jsonl", help="Path to `ledger.jsonl`.")
    p.add_argument("--workdir", default="", help="Experiment root directory (defaults to manifest parent).")
    p.add_argument("--plots-dir", default="plots", help="Directory containing `plot_*.py` scripts.")
    p.add_argument("--figures-dir", default="figures", help="Directory containing rendered `.pdf`/`.png` figures.")
    p.add_argument("--results-md", default="", help="Optional path to `07_exp_results.md` for `@evidence` verification.")
    p.add_argument("--out", default="", help="Optional path to write Markdown audit report.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    base_dir = Path(args.workdir).resolve() if args.workdir else manifest_path.parent
    ledger_path = (base_dir / args.ledger).resolve() if not Path(args.ledger).is_absolute() else Path(args.ledger).resolve()
    plots_dir = (base_dir / args.plots_dir).resolve() if args.plots_dir else None
    figures_dir = (base_dir / args.figures_dir).resolve() if args.figures_dir else None
    results_md = (base_dir / args.results_md).resolve() if args.results_md else None

    rep = run_audit(manifest_path, ledger_path, base_dir, plots_dir, figures_dir, results_md)
    if args.out:
        out_p = Path(args.out).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(format_markdown_report(rep), encoding="utf-8")

    print(json.dumps(asdict(rep), indent=2, ensure_ascii=False))
    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
