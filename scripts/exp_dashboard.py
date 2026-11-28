#!/usr/bin/env python3
"""Zero-token deterministic live Kanban dashboard for Stage 7B experiment monitoring.

Eliminates LLM polling loops (`schedule` context bloat) and prevents accidental agent
interference with live experiments. Runs locally on the host machine (`http://127.0.0.1:8765`),
fetching a lightweight read-only snapshot from either:
- A remote GPU server (via `workspaces/<project>/.remote_host.json` over SSH, cached by TTL), or
- A local `workspaces/<project>/experiments/` directory (`--local`).

Features:
1. Live hardware telemetry (GPU utilization, VRAM, temperature, Host CPU RAM, Disk free GB).
2. Manifest + append-only `ledger.jsonl` reconciliation: overall & per-batch progress bars,
   currently `RUNNING` condition(s) with live elapsed wall-clock minutes, completed metrics table,
   failed/invalidated alerts, and live tail of the active condition's log file.
3. `--once` CLI mode outputs the structured JSON snapshot and exits immediately.

Zero third-party dependencies (Python 3.10+ standard library `http.server` only).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any

try:
    from scripts.remote_gpu import SshRunner, default_ssh_runner, load_profile, posix_quote, profile_path_for
    from scripts.run_matrix import load_ledger_records, resolve_effective_states
except ModuleNotFoundError:
    from remote_gpu import SshRunner, default_ssh_runner, load_profile, posix_quote, profile_path_for  # type: ignore[no-redef]
    from run_matrix import load_ledger_records, resolve_effective_states  # type: ignore[no-redef]


def _elapsed_minutes(iso_ts: str) -> float:
    if not iso_ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return round(max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0), 1)
    except Exception:
        return 0.0


def summarize_manifest_and_ledger(
    manifest_data: dict[str, Any] | None,
    ledger_records: list[dict[str, Any]],
) -> dict[str, Any]:
    states = resolve_effective_states(ledger_records)
    runs = (manifest_data or {}).get("runs") or []

    counts = {"completed": 0, "running": 0, "failed": 0, "invalidated": 0, "pending": 0}
    batches: dict[str, dict[str, int]] = {}
    active_runs: list[dict[str, Any]] = []
    recent_completed: list[dict[str, Any]] = []
    failed_runs: list[dict[str, Any]] = []
    wall_secs: list[float] = []

    items_iter = runs if runs else [{"condition_id": cid, "tier": "ad-hoc"} for cid in states]
    for item in items_iter:
        cid = str(item.get("condition_id", "")).strip()
        batch_key = str(item.get("batch") or item.get("tier") or cid.split("__")[0] or "default")
        b_stat = batches.setdefault(batch_key, {"total": 0, "completed": 0, "running": 0, "failed": 0, "pending": 0})
        b_stat["total"] += 1

        st = states.get(cid)
        if not st:
            counts["pending"] += 1
            b_stat["pending"] += 1
            continue

        raw_status = str(st.get("status", ""))
        if raw_status == "started":
            counts["running"] += 1
            b_stat["running"] += 1
            active_runs.append(
                {
                    "condition_id": cid,
                    "gpu": st.get("gpu", ""),
                    "started_at": st.get("timestamp", ""),
                    "elapsed_min": _elapsed_minutes(str(st.get("timestamp", ""))),
                    "log_file": st.get("log_file", ""),
                }
            )
        elif raw_status == "completed":
            counts["completed"] += 1
            b_stat["completed"] += 1
            w = st.get("wall_sec")
            if isinstance(w, (int, float)):
                wall_secs.append(float(w))
            metrics = st.get("metrics") if isinstance(st.get("metrics"), dict) else {}
            flat_metrics = {
                k: round(float(v), 4)
                for k, v in list(metrics.items())[:6]
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            recent_completed.append(
                {
                    "condition_id": cid,
                    "wall_sec": w,
                    "timestamp": st.get("timestamp", ""),
                    "metrics": flat_metrics,
                }
            )
        elif raw_status == "failed":
            counts["failed"] += 1
            b_stat["failed"] += 1
            failed_runs.append(
                {
                    "condition_id": cid,
                    "exit_code": st.get("exit_code"),
                    "error": st.get("error", ""),
                    "timestamp": st.get("timestamp", ""),
                }
            )
        elif raw_status == "invalidated":
            counts["invalidated"] += 1
            b_stat["pending"] += 1
        else:
            counts["pending"] += 1
            b_stat["pending"] += 1

    recent_completed.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
    total = len(items_iter)
    mean_wall = round(sum(wall_secs) / len(wall_secs), 1) if wall_secs else 0.0
    rem = max(0, total - counts["completed"])
    eta_hours = round((rem * mean_wall) / 3600.0, 2) if mean_wall > 0 else None

    return {
        "total_planned": total,
        "counts": counts,
        "mean_wall_sec": mean_wall,
        "eta_single_worker_hours": eta_hours,
        "batches": batches,
        "active_runs": active_runs,
        "recent_completed": recent_completed[:15],
        "failed_runs": failed_runs[:15],
    }


def collect_local_snapshot(workspace: Path, exp_subdir: str = "experiments") -> dict[str, Any]:
    exp_dir = (workspace / exp_subdir).resolve()
    manifest_p = exp_dir / "exp_manifest.json"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.is_file() else None

    ledger_p = exp_dir / "results" / "ledger.jsonl"
    records = load_ledger_records(ledger_p)
    summary = summarize_manifest_and_ledger(manifest_data, records)

    active_tail = ""
    if summary["active_runs"]:
        lf_rel = summary["active_runs"][0].get("log_file") or ""
        lf_path = (exp_dir / lf_rel).resolve() if lf_rel else Path()
        if lf_path.is_file():
            raw = lf_path.read_bytes()[-16384:].decode("utf-8", errors="replace").splitlines()
            active_tail = "\n".join(raw[-35:])

    usage = shutil.disk_usage(workspace if workspace.exists() else Path.cwd())
    return {
        "mode": "local",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "host": "localhost",
        "job_state": "RUNNING" if summary["counts"]["running"] > 0 else "IDLE",
        "gpus": [],
        "ram_used_gb": None,
        "ram_total_gb": None,
        "disk_free_gb": round(usage.free / (1024**3), 2),
        "summary": summary,
        "active_log_tail": active_tail,
    }


def build_remote_snapshot_script(remote_dir: str, exp_subdir: str, job_id: str) -> str:
    return f"""python3 - {posix_quote(remote_dir)} {posix_quote(exp_subdir)} {posix_quote(job_id)} <<'PY'
import json, os, shutil, subprocess, sys

remote_dir, exp_sub, job_id = sys.argv[1], sys.argv[2], sys.argv[3]
exp_dir = os.path.join(remote_dir, exp_sub) if exp_sub else remote_dir

gpus = []
try:
    r = subprocess.run(
        "nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits",
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=6
    )
    if r.returncode == 0:
        for ln in r.stdout.strip().splitlines():
            ps = [x.strip() for x in ln.split(",")]
            if len(ps) >= 6:
                gpus.append({{
                    "index": int(ps[0]),
                    "name": ps[1],
                    "gpu_util_pct": int(float(ps[2])),
                    "vram_used_mb": int(float(ps[3])),
                    "vram_total_mb": int(float(ps[4])),
                    "temp_c": int(float(ps[5])),
                }})
except Exception:
    pass

ram_total_gb, ram_used_gb = 0.0, 0.0
if os.path.exists("/proc/meminfo"):
    info = {{}}
    for ln in open("/proc/meminfo", encoding="utf-8", errors="ignore"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            ns = [int(x) for x in v.split() if x.isdigit()]
            if ns: info[k.strip()] = ns[0]
    ram_total_gb = round(info.get("MemTotal", 0) / (1024**2), 2)
    avail_gb = info.get("MemAvailable", 0) / (1024**2)
    ram_used_gb = round(max(0.0, ram_total_gb - avail_gb), 2)

disk_free_gb = round(shutil.disk_usage(remote_dir).free / (1024**3), 2) if os.path.exists(remote_dir) else 0.0

job_state = "UNKNOWN"
job_dir = os.path.join(remote_dir, ".rf_jobs", job_id)
if os.path.isdir(job_dir):
    pid_p = os.path.join(job_dir, "pid")
    ec_p = os.path.join(job_dir, "exit_code")
    pid_s = open(pid_p).read().strip() if os.path.exists(pid_p) else ""
    if pid_s.isdigit() and os.path.exists(f"/proc/{{pid_s}}"):
        job_state = "RUNNING"
    elif os.path.exists(ec_p):
        ec = open(ec_p).read().strip()
        job_state = "COMPLETED" if ec == "0" else f"FAILED(exit={{ec}})"
    else:
        job_state = "STOPPED"

manifest_data = None
for cand in [os.path.join(exp_dir, "exp_manifest.json"), os.path.join(remote_dir, "exp_manifest.json")]:
    if os.path.isfile(cand):
        try: manifest_data = json.loads(open(cand, encoding="utf-8").read()); break
        except Exception: pass

ledger_lines = []
ledger_dir = exp_dir
for lcand in [
    os.path.join(exp_dir, "results", "ledger.jsonl"),
    os.path.join(remote_dir, "storage", "results", "ledger.jsonl"),
    os.path.join(remote_dir, "results", "ledger.jsonl"),
]:
    if os.path.isfile(lcand):
        ledger_dir = os.path.dirname(os.path.dirname(lcand))
        for ln in open(lcand, encoding="utf-8", errors="ignore"):
            if ln.strip():
                try: ledger_lines.append(json.loads(ln))
                except Exception: pass
        break

active_log_rel = ""
for rec in reversed(ledger_lines):
    if rec.get("status") == "started" and rec.get("log_file"):
        active_log_rel = rec["log_file"]
        break

log_tail = ""
for log_cand in [
    os.path.join(exp_dir, active_log_rel) if active_log_rel else "",
    os.path.join(ledger_dir, active_log_rel) if active_log_rel else "",
    os.path.join(job_dir, "stdout.log"),
]:
    if log_cand and os.path.isfile(log_cand):
        sz = os.path.getsize(log_cand)
        with open(log_cand, "rb") as f:
            f.seek(max(0, sz - 16384))
            log_tail = "\\n".join(f.read().decode("utf-8", errors="replace").splitlines()[-35:])
        break

print(json.dumps({{
    "job_state": job_state,
    "gpus": gpus,
    "ram_used_gb": ram_used_gb,
    "ram_total_gb": ram_total_gb,
    "disk_free_gb": disk_free_gb,
    "manifest": manifest_data,
    "ledger": ledger_lines,
    "active_log_tail": log_tail,
}}, ensure_ascii=False))
PY"""


def collect_remote_snapshot(
    workspace: Path,
    exp_subdir: str = "experiments",
    job_id: str = "main_exp",
    runner: SshRunner = default_ssh_runner,
) -> dict[str, Any]:
    profile = load_profile(workspace)
    script = build_remote_snapshot_script(profile.remote_dir, exp_subdir, job_id)
    res = runner(profile, script, None, 25)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace").strip()
        return {
            "mode": "remote",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "host": f"{profile.host}:{profile.port}",
            "job_state": "SSH_ERROR",
            "error": err,
            "gpus": [],
            "summary": summarize_manifest_and_ledger(None, []),
            "active_log_tail": "",
        }
    raw_obj = json.loads(res.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    local_manifest_p = (workspace / exp_subdir / "exp_manifest.json").resolve()
    manifest = raw_obj.get("manifest") or (
        json.loads(local_manifest_p.read_text(encoding="utf-8")) if local_manifest_p.is_file() else None
    )
    summary = summarize_manifest_and_ledger(manifest, raw_obj.get("ledger") or [])
    return {
        "mode": "remote",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "host": f"{profile.host}:{profile.port}",
        "job_state": raw_obj.get("job_state", "UNKNOWN"),
        "gpus": raw_obj.get("gpus", []),
        "ram_used_gb": raw_obj.get("ram_used_gb"),
        "ram_total_gb": raw_obj.get("ram_total_gb"),
        "disk_free_gb": raw_obj.get("disk_free_gb"),
        "summary": summary,
        "active_log_tail": raw_obj.get("active_log_tail", ""),
    }


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>ResearchFlow · Live Experiment Kanban</title>
  <style>
    :root { --bg:#0f172a; --card:#1e293b; --border:#334155; --txt:#f1f5f9; --muted:#94a3b8; --ok:#10b981; --run:#38bdf8; --err:#ef4444; --warn:#f59e0b; }
    * { box-sizing:border-box; }
    body { margin:0; padding:24px; font-family:ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--txt); }
    .top { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
    h1 { margin:0; font-size:20px; font-weight:700; }
    .badge { padding:4px 10px; border-radius:999px; font-size:12px; font-weight:600; background:#334155; }
    .badge.RUNNING { background:rgba(56,189,248,.18); color:var(--run); border:1px solid var(--run); }
    .badge.COMPLETED { background:rgba(16,185,129,.18); color:var(--ok); border:1px solid var(--ok); }
    .badge.FAILED, .badge.SSH_ERROR { background:rgba(239,68,68,.18); color:var(--err); border:1px solid var(--err); }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-bottom:18px; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; }
    .label { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
    .val { font-size:24px; font-weight:700; margin-top:6px; }
    .sub { font-size:12px; color:var(--muted); margin-top:4px; }
    .bar { height:10px; background:#0b1120; border-radius:999px; overflow:hidden; margin-top:8px; }
    .fill { height:100%; background:linear-gradient(90deg,#38bdf8,#10b981); transition:width .3s; }
    .two { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:18px; }
    @media (max-width:960px) { .two { grid-template-columns:1fr; } }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--border); }
    th { color:var(--muted); font-weight:600; }
    pre { background:#0b1120; border:1px solid var(--border); border-radius:8px; padding:12px; font-size:12px; line-height:1.45; overflow-x:auto; max-height:340px; color:#cbd5e1; margin:8px 0 0; }
    code { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; }
  </style>
</head>
<body>
  <div class="top">
    <div>
      <h1>ResearchFlow · Deterministic Live Kanban</h1>
      <div class="sub" id="meta">Connecting...</div>
    </div>
    <div><span class="badge" id="stateBadge">LOADING</span></div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="label">Overall Progress</div>
      <div class="val" id="progVal">- / -</div>
      <div class="bar"><div class="fill" id="progBar" style="width:0%"></div></div>
      <div class="sub" id="progSub">Waiting for snapshot...</div>
    </div>
    <div class="card">
      <div class="label">GPU Telemetry</div>
      <div class="val" id="gpuVal">-</div>
      <div class="sub" id="gpuSub">-</div>
    </div>
    <div class="card">
      <div class="label">Host RAM & Disk</div>
      <div class="val" id="sysVal">-</div>
      <div class="sub" id="sysSub">-</div>
    </div>
    <div class="card">
      <div class="label">Active Condition</div>
      <div class="val" id="actVal" style="font-size:15px;word-break:break-all;">None</div>
      <div class="sub" id="actSub">-</div>
    </div>
  </div>

  <div class="two">
    <div class="card">
      <div class="label" style="margin-bottom:8px;">Batch / Tier Progress</div>
      <table><thead><tr><th>Batch</th><th>Done</th><th>Run</th><th>Fail</th><th>Bar</th></tr></thead><tbody id="batchBody"></tbody></table>
    </div>
    <div class="card">
      <div class="label" style="margin-bottom:8px;">Latest Completed Runs (Read-Only)</div>
      <table><thead><tr><th>Condition</th><th>Time</th><th>Key Metrics</th></tr></thead><tbody id="doneBody"></tbody></table>
    </div>
  </div>

  <div class="card">
    <div class="label">Live Active Runner Log Tail (Zero Agent Tokens)</div>
    <pre id="logBox">Waiting for log stream...</pre>
  </div>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/snapshot');
    const d = await r.json();
    const s = d.summary || {};
    const c = s.counts || {};
    const tot = s.total_planned || 0;
    const done = c.completed || 0;
    const pct = tot > 0 ? Math.round((done / tot) * 100) : 0;

    document.getElementById('meta').textContent = `Host: ${d.host} (${d.mode}) · Updated: ${new Date(d.fetched_at).toLocaleTimeString()}`;
    const b = document.getElementById('stateBadge');
    b.textContent = d.job_state || 'UNKNOWN';
    b.className = 'badge ' + (d.job_state || '').split('(')[0];

    document.getElementById('progVal').textContent = `${done} / ${tot} (${pct}%)`;
    document.getElementById('progBar').style.width = pct + '%';
    document.getElementById('progSub').textContent = `Running: ${c.running||0} · Failed: ${c.failed||0} · Mean: ${s.mean_wall_sec||0}s` + (s.eta_single_worker_hours !== null ? ` · ~ETA: ${s.eta_single_worker_hours}h` : '');

    if (d.gpus && d.gpus.length > 0) {
      const g = d.gpus[0];
      document.getElementById('gpuVal').textContent = `${g.gpu_util_pct}% Util · ${(g.vram_used_mb/1024).toFixed(1)}/${(g.vram_total_mb/1024).toFixed(1)} GB`;
      document.getElementById('gpuSub').textContent = `${g.name} (${g.temp_c}°C)` + (d.gpus.length > 1 ? ` +${d.gpus.length-1} more` : '');
    } else {
      document.getElementById('gpuVal').textContent = 'Local / N/A';
      document.getElementById('gpuSub').textContent = 'No GPU telemetry';
    }

    const ramTxt = d.ram_total_gb ? `RAM ${d.ram_used_gb}/${d.ram_total_gb} GB` : 'RAM N/A';
    document.getElementById('sysVal').textContent = `Disk ${d.disk_free_gb ?? '-'} GB free`;
    document.getElementById('sysSub').textContent = ramTxt;

    if (s.active_runs && s.active_runs.length > 0) {
      const a = s.active_runs[0];
      document.getElementById('actVal').textContent = a.condition_id;
      document.getElementById('actSub').textContent = `Elapsed: ${a.elapsed_min} min` + (a.gpu !== '' ? ` · GPU ${a.gpu}` : '');
    } else {
      document.getElementById('actVal').textContent = 'Idle';
      document.getElementById('actSub').textContent = '-';
    }

    const bb = document.getElementById('batchBody');
    bb.innerHTML = '';
    for (const [bname, st] of Object.entries(s.batches || {})) {
      const bp = st.total > 0 ? Math.round((st.completed / st.total) * 100) : 0;
      bb.innerHTML += `<tr><td><code>${bname}</code></td><td>${st.completed}/${st.total}</td><td>${st.running}</td><td>${st.failed}</td><td style="width:90px"><div class="bar" style="margin:0"><div class="fill" style="width:${bp}%"></div></div></td></tr>`;
    }

    const db = document.getElementById('doneBody');
    db.innerHTML = '';
    for (const item of (s.recent_completed || []).slice(0, 8)) {
      const mstr = Object.entries(item.metrics || {}).map(([k,v]) => `${k}=${v}`).join(', ');
      db.innerHTML += `<tr><td><code>${item.condition_id}</code></td><td>${item.wall_sec ?? '-'}s</td><td><code>${mstr}</code></td></tr>`;
    }
    document.getElementById('logBox').textContent = d.active_log_tail || d.error || '(No active log output)';
  } catch (e) {
    document.getElementById('meta').textContent = 'Refresh error: ' + e;
  }
}
refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""


class SnapshotCache:
    def __init__(self, workspace: Path, exp_subdir: str, job_id: str, force_local: bool, ttl_sec: float = 12.0) -> None:
        self.workspace = workspace
        self.exp_subdir = exp_subdir
        self.job_id = job_id
        self.force_local = force_local
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._last_ts = 0.0
        self._cached: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and (now - self._last_ts) < self.ttl_sec:
                return self._cached
            use_remote = (not self.force_local) and profile_path_for(self.workspace).is_file()
            snap = (
                collect_remote_snapshot(self.workspace, self.exp_subdir, self.job_id)
                if use_remote
                else collect_local_snapshot(self.workspace, self.exp_subdir)
            )
            self._cached = snap
            self._last_ts = time.monotonic()
            return snap


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ResearchFlow deterministic zero-token experiment Kanban dashboard.")
    p.add_argument("--workspace", required=True, help="Path to `workspaces/<project>`.")
    p.add_argument("--exp-subdir", default="experiments", help="Experiment directory inside workspace.")
    p.add_argument("--job-id", default="main_exp", help="Remote job ID when `.remote_host.json` exists.")
    p.add_argument("--local", action="store_true", help="Monitor local workspace files instead of remote SSH.")
    p.add_argument("--host", default="127.0.0.1", help="Local bind address (default: 127.0.0.1).")
    p.add_argument("--port", type=int, default=8765, help="Local HTTP port (default: 8765).")
    p.add_argument("--ttl", type=float, default=12.0, help="Minimum seconds between remote SSH polls.")
    p.add_argument("--once", action="store_true", help="Print a single JSON snapshot to stdout and exit.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ws = Path(args.workspace).resolve()
    cache = SnapshotCache(ws, args.exp_subdir, args.job_id, force_local=args.local, ttl_sec=args.ttl)

    if args.once:
        print(json.dumps(cache.get(), indent=2, ensure_ascii=False))
        return 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/snapshot"):
                body = json.dumps(cache.get(), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = DASHBOARD_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, format: str, *log_args: Any) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ResearchFlow Live Kanban running at http://{args.host}:{args.port} (workspace={ws.name})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
