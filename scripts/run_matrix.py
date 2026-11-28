#!/usr/bin/env python3
"""Domain-agnostic multi-GPU experiment queue runner & append-only ledger manager.

Philosophy:
- Generic tools enforce the execution & provenance protocol; project scripts define domain logic.
- Each planned experiment unit in `exp_manifest.json` is an opaque shell command + `condition_id`
  + expected `metrics_file` path. Works identically for LLM continual learning, 3DGS, reasoning,
  multimodal VLM, or API-based agent benchmarks.

Key capabilities:
1. `run`        : Schedules pending/failed/invalidated `condition_id`s across 1..N GPUs in parallel
                  (`--gpus 0,1,2,3` or `--workers N` for CPU/API runs), skipping conditions that
                  already have a valid `completed` entry in the append-only `ledger.jsonl`.
                  Atomically updates `progress.json` after every state transition for `remote_gpu.py status`.
2. `invalidate` : Appends `invalidated` tombstone records to `ledger.jsonl` (never deleting history!)
                  when a shared/common code bug is fixed, ensuring pre-bugfix and post-bugfix runs
                  are never mixed in final tables.
3. `summary`    : Prints live completion/failure/invalidation counts from `manifest` + `ledger`.

Zero third-party dependencies (Python 3.10+ standard library only).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def current_git_commit(cwd: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "unversioned"


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError(f"Manifest {manifest_path} must contain a non-empty 'runs' list.")
    seen: set[str] = set()
    for item in runs:
        cid = str(item.get("condition_id", "")).strip()
        cmd = str(item.get("command", "")).strip()
        if not cid or not cmd:
            raise ValueError(f"Every run in {manifest_path} requires non-empty 'condition_id' and 'command'.")
        if cid in seen:
            raise ValueError(f"Duplicate condition_id in manifest: {cid!r}")
        seen.add(cid)
    return data


def load_ledger_records(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for lineno, raw in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupted JSONL in {ledger_path}:{lineno}: {exc}") from exc
    return records


def resolve_effective_states(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse append-only ledger events into the latest terminal/active state per `condition_id`."""
    latest: dict[str, dict[str, Any]] = {}
    for rec in records:
        cid = str(rec.get("condition_id", "")).strip()
        if not cid:
            continue
        status = str(rec.get("status", ""))
        if status == "invalidated":
            prev = dict(latest.get(cid, {}))
            prev["status"] = "invalidated"
            prev["invalidated_at"] = rec.get("timestamp", "")
            prev["invalidation_reason"] = rec.get("reason", "")
            latest[cid] = prev
        else:
            latest[cid] = dict(rec)
    return latest


class LedgerWriter:
    """Thread-safe append-only JSONL ledger + atomic `progress.json` writer."""

    def __init__(self, ledger_path: Path, progress_path: Path | None, total_runs: int) -> None:
        self.ledger_path = ledger_path
        self.progress_path = progress_path
        self.total_runs = total_runs
        self._lock = threading.Lock()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if self.progress_path:
            self.progress_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with self.ledger_path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            if self.progress_path:
                self._write_progress_unlocked()

    def _write_progress_unlocked(self) -> None:
        assert self.progress_path is not None
        recs = load_ledger_records(self.ledger_path)
        states = resolve_effective_states(recs)
        counts = {"completed": 0, "failed": 0, "running": 0, "invalidated": 0}
        wall_times: list[float] = []
        for st in states.values():
            s = str(st.get("status", ""))
            if s == "started":
                counts["running"] += 1
            elif s in counts:
                counts[s] += 1
            if s == "completed" and isinstance(st.get("wall_sec"), (int, float)):
                wall_times.append(float(st["wall_sec"]))

        remaining = max(0, self.total_runs - counts["completed"])
        avg_sec = (sum(wall_times) / len(wall_times)) if wall_times else 0.0
        snap = {
            "updated_at": utc_now_iso(),
            "total_planned": self.total_runs,
            "completed": counts["completed"],
            "running": counts["running"],
            "failed": counts["failed"],
            "invalidated": counts["invalidated"],
            "remaining": remaining,
            "mean_completed_wall_sec": round(avg_sec, 2),
        }
        tmp = self.progress_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.progress_path)


def verify_evaluator_lock(manifest: dict[str, Any], base_dir: Path) -> tuple[str, str]:
    eval_rel = str(manifest.get("evaluator_path", "")).strip()
    expected_sha = str(manifest.get("evaluator_sha256", "")).strip()
    if not eval_rel:
        return "", ""
    eval_path = (base_dir / eval_rel).resolve()
    if not eval_path.is_file():
        raise FileNotFoundError(f"Evaluator script declared in manifest not found: {eval_path}")
    actual_sha = sha256_file(eval_path)
    if expected_sha and actual_sha.lower() != expected_sha.lower():
        raise RuntimeError(
            f"Evaluator SHA-256 mismatch for {eval_rel}: expected {expected_sha}, got {actual_sha}. "
            "Evaluation harness was modified after manifest lock!"
        )
    return eval_rel, actual_sha


def execute_one_condition(
    item: dict[str, Any],
    base_dir: Path,
    log_dir: Path,
    gpu_slot: str | None,
    writer: LedgerWriter,
    git_sha: str,
    eval_sha: str,
) -> dict[str, Any]:
    cid = str(item["condition_id"]).strip()
    raw_cmd = item["command"]
    if isinstance(raw_cmd, list):
        cmd = subprocess.list2cmdline([str(x) for x in raw_cmd]) if os.name == "nt" else shlex.join([str(x) for x in raw_cmd])
    else:
        cmd = str(raw_cmd).strip()
    metrics_rel = str(item.get("metrics_file", "")).strip()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", cid)
    log_file = log_dir / f"{safe_name}.log"
    log_dir.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    writer.append(
        {
            "condition_id": cid,
            "status": "started",
            "gpu": gpu_slot if gpu_slot is not None else "",
            "git_commit": git_sha,
            "evaluator_sha256": eval_sha,
            "command": cmd,
            "log_file": str(log_file.relative_to(base_dir).as_posix()) if log_file.is_relative_to(base_dir) else str(log_file),
            "timestamp": started_at,
        }
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if os.name != "nt":
        tmp_dir = base_dir / ".cache" / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault("TMPDIR", str(tmp_dir))
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    if gpu_slot is not None:
        env["CUDA_VISIBLE_DEVICES"] = gpu_slot
    custom_env = item.get("env")
    if isinstance(custom_env, dict):
        for k, v in custom_env.items():
            if v is None or v == "":
                env.pop(str(k), None)
            else:
                env[str(k)] = str(v)

    t0 = time.monotonic()
    with log_file.open("ab") as lf:
        header = f"\n=== [ResearchFlow run_matrix] {cid} | start={started_at} | gpu={gpu_slot} | commit={git_sha} ===\n"
        lf.write(header.encode("utf-8"))
        lf.flush()
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(base_dir),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            check=False,
        )
    wall_sec = round(time.monotonic() - t0, 3)

    metrics_data: dict[str, Any] | None = None
    metrics_err = ""
    if proc.returncode == 0 and metrics_rel:
        m_path = (base_dir / metrics_rel).resolve()
        if not m_path.is_file():
            metrics_err = f"Declared metrics_file missing after exit 0: {metrics_rel}"
        else:
            try:
                metrics_data = json.loads(m_path.read_text(encoding="utf-8"))
            except Exception as exc:
                metrics_err = f"Failed to parse metrics_file {metrics_rel}: {exc}"

    final_status = "completed" if (proc.returncode == 0 and not metrics_err) else "failed"
    rec: dict[str, Any] = {
        "condition_id": cid,
        "status": final_status,
        "exit_code": proc.returncode,
        "wall_sec": wall_sec,
        "gpu": gpu_slot if gpu_slot is not None else "",
        "git_commit": git_sha,
        "evaluator_sha256": eval_sha,
        "method": item.get("method", ""),
        "benchmark": item.get("benchmark", ""),
        "seed": item.get("seed"),
        "tier": item.get("tier", "main"),
        "metrics_file": metrics_rel,
        "metrics": metrics_data,
        "error": metrics_err,
        "timestamp": utc_now_iso(),
    }
    writer.append(rec)
    return rec


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest).resolve()
    base_dir = Path(args.workdir).resolve() if args.workdir else manifest_path.parent
    ledger_path = (base_dir / args.ledger).resolve() if not Path(args.ledger).is_absolute() else Path(args.ledger).resolve()
    progress_path = (base_dir / args.progress).resolve() if args.progress else ledger_path.parent / "progress.json"
    log_dir = ledger_path.parent / "logs"

    manifest = load_manifest(manifest_path)
    _, eval_sha = verify_evaluator_lock(manifest, base_dir)
    git_sha = args.commit or current_git_commit(base_dir)

    existing_states = resolve_effective_states(load_ledger_records(ledger_path))
    only_filter = set(args.only or ())

    pending_items: list[dict[str, Any]] = []
    skipped_completed = 0
    for item in manifest["runs"]:
        cid = str(item["condition_id"]).strip()
        if only_filter and cid not in only_filter:
            continue
        if args.tier and str(item.get("tier", "main")) != args.tier:
            continue
        st = existing_states.get(cid)
        if st and st.get("status") == "completed" and not args.force:
            skipped_completed += 1
            continue
        pending_items.append(item)

    writer = LedgerWriter(ledger_path, progress_path, total_runs=len(manifest["runs"]))
    if not pending_items:
        return {
            "status": "ok",
            "executed": 0,
            "skipped_completed": skipped_completed,
            "completed_now": 0,
            "failed_now": 0,
        }

    gpu_list = [g.strip() for g in (args.gpus or "").split(",") if g.strip()]
    num_workers = len(gpu_list) if gpu_list else max(1, int(args.workers))
    slot_queue: queue.Queue[str | None] = queue.Queue()
    if gpu_list:
        for g in gpu_list:
            slot_queue.put(g)
    else:
        for _ in range(num_workers):
            slot_queue.put(None)

    def worker_task(run_item: dict[str, Any]) -> dict[str, Any]:
        slot = slot_queue.get()
        try:
            return execute_one_condition(run_item, base_dir, log_dir, slot, writer, git_sha, eval_sha)
        finally:
            slot_queue.put(slot)

    completed_now = 0
    failed_now = 0
    failed_ids: list[str] = []
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = [pool.submit(worker_task, it) for it in pending_items]
        for fut in as_completed(futures):
            res = fut.result()
            if res["status"] == "completed":
                completed_now += 1
            else:
                failed_now += 1
                failed_ids.append(str(res["condition_id"]))

    return {
        "status": "ok" if failed_now == 0 else "partial_failure",
        "executed": len(pending_items),
        "skipped_completed": skipped_completed,
        "completed_now": completed_now,
        "failed_now": failed_now,
        "failed_conditions": sorted(failed_ids),
        "ledger": str(ledger_path),
        "progress": str(progress_path),
    }


def cmd_invalidate(args: argparse.Namespace) -> dict[str, Any]:
    ledger_path = Path(args.ledger).resolve()
    records = load_ledger_records(ledger_path)
    states = resolve_effective_states(records)
    regex = re.compile(args.pattern)
    matched: list[str] = []

    writer = LedgerWriter(ledger_path, progress_path=None, total_runs=len(states))
    now = utc_now_iso()
    for cid, st in sorted(states.items()):
        if st.get("status") == "invalidated":
            continue
        if regex.search(cid):
            writer.append(
                {
                    "condition_id": cid,
                    "status": "invalidated",
                    "reason": args.reason,
                    "superseded_commit": st.get("git_commit", ""),
                    "timestamp": now,
                }
            )
            matched.append(cid)

    return {"status": "ok", "invalidated_count": len(matched), "invalidated_conditions": matched}


def cmd_summary(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(Path(args.manifest).resolve())
    ledger_path = Path(args.ledger).resolve()
    states = resolve_effective_states(load_ledger_records(ledger_path))

    buckets: dict[str, list[str]] = {"completed": [], "failed": [], "running": [], "invalidated": [], "pending": []}
    for item in manifest["runs"]:
        cid = str(item["condition_id"]).strip()
        st = states.get(cid)
        if not st:
            buckets["pending"].append(cid)
        else:
            s = str(st.get("status", ""))
            if s == "started":
                buckets["running"].append(cid)
            elif s in buckets:
                buckets[s].append(cid)
            else:
                buckets["pending"].append(cid)

    return {
        "total_planned": len(manifest["runs"]),
        "counts": {k: len(v) for k, v in buckets.items()},
        "failed_conditions": buckets["failed"],
        "invalidated_conditions": buckets["invalidated"],
        "pending_conditions": buckets["pending"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ResearchFlow multi-GPU experiment queue & append-only ledger CLI.")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_run = sub.add_parser("run", help="Execute pending/failed/invalidated runs across 1..N GPUs.")
    p_run.add_argument("--manifest", required=True, help="Path to `exp_manifest.json`.")
    p_run.add_argument("--ledger", default="results/ledger.jsonl", help="Path to append-only `ledger.jsonl`.")
    p_run.add_argument("--progress", default="", help="Optional path to atomic `progress.json`.")
    p_run.add_argument("--workdir", default="", help="Working directory for run commands (defaults to manifest dir).")
    p_run.add_argument("--gpus", default="", help="Comma-separated GPU IDs, e.g. `0` or `0,1,2,3`.")
    p_run.add_argument("--workers", type=int, default=1, help="Worker count when `--gpus` is omitted (CPU/API runs).")
    p_run.add_argument("--tier", default="", help="Optional tier filter (e.g. `main`, `ablation`, `probe`).")
    p_run.add_argument("--only", action="append", default=[], help="Run only specific `condition_id`(s).")
    p_run.add_argument("--commit", default="", help="Explicit git commit tag when running on synced remote dir.")
    p_run.add_argument("--force", action="store_true", help="Re-run even already `completed` conditions.")

    p_inv = sub.add_parser("invalidate", help="Mark matching ledger entries as `invalidated` after shared bugfixes.")
    p_inv.add_argument("--ledger", required=True, help="Path to `ledger.jsonl`.")
    p_inv.add_argument("--pattern", required=True, help="Regex matching `condition_id`s to invalidate.")
    p_inv.add_argument("--reason", required=True, help="Audit reason for invalidation (e.g. shared tokenizer fix).")

    p_sum = sub.add_parser("summary", help="Summarize manifest coverage against `ledger.jsonl`.")
    p_sum.add_argument("--manifest", required=True)
    p_sum.add_argument("--ledger", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {"run": cmd_run, "invalidate": cmd_invalidate, "summary": cmd_summary}
    try:
        out = dispatch[args.subcommand](args)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0 if out.get("status") != "partial_failure" else 2
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
