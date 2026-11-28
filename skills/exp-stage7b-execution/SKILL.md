---
name: exp-stage7b-execution
description: Stage 7B of ResearchFlow Experimentation. Dispatches multi-GPU/remote queues via remote_gpu.py and run_matrix.py, launches the zero-token deterministic local Kanban dashboard (exp_dashboard.py), enforces a strict Read-Only Live Inspection rule unless authorized, applies 3-class triage with append-only version invalidation, renders data figures, and runs audit_exp.py.
---

# Stage 7B — 多卡断点执行、零 Token 实时看板与实验保真审计 (`exp-stage7b-execution`)

本技能承接通过最终盲审锁版的 `experiments/` 代码与 `exp_manifest.json`，负责**启动远端单卡/多卡守护队列、提供零 Token 消耗的确定性实时看板、严守在线实验只读边界处理异常、并在跑完后渲染确定性实验图表与执行七维审计**，交付 `07_exp_results.md`。

---

## 一、Step 1：挂起守护队列 + 启动本地零 Token 实时看板（告别 Agent 高频轮询刷屏）

1. **推送代码与启动远端多卡/单卡守护队列**：
   ```bash
   python scripts/remote_gpu.py push --workspace workspaces/<project> --src experiments
   python scripts/remote_gpu.py push --workspace workspaces/<project> --src ../../scripts/run_matrix.py --dest experiments/run_matrix.py
   python scripts/remote_gpu.py launch --workspace workspaces/<project> --job-id main_exp --workdir experiments \
     --cmd "python run_matrix.py run --manifest exp_manifest.json --ledger results/ledger.jsonl --gpus 0 --commit $(git rev-parse --short=12 HEAD)"
   ```
   - 若服务器有多张空闲 GPU（如 `4× 4090`），直接传 `--gpus 0,1,2,3`，`run_matrix.py` 会自动开启工作池动态负载均衡各独立 `condition_id`，并通过只增不删的 `results/ledger.jsonl` 与原子 `results/progress.json` 支持任意时刻幂等断点续跑。
2. **启动本地确定性实时看板（`scripts/exp_dashboard.py` — 零 Agent Token 消耗！）**：
   - 开跑确认首轮启动正常后，在本机后台守护启动轻量 Web 看板（使用 `run_command(..., IsDaemon=true)`），并把本地浏览器地址直接发给用户：
     ```bash
     python scripts/exp_dashboard.py --workspace workspaces/<project> --job-id main_exp --port 8765
     ```
   - 用户随时打开 `http://127.0.0.1:8765` 即可实时查看远端 GPU 利用率/显存、主机内存/磁盘余量、总进度与分批进度条、当前运行条件的已耗时分钟数、已完成结果指标及实时滚动日志末尾——**全程由确定性 Python 程序完成，消耗 0 个 LLM Token**！
   - **严禁挂 2–5 分钟短周期 `schedule` 定时器反复刷屏撑爆上下文**！若用户希望 Agent 也在后台兜底关注，仅按总预算跨度设置极低频（如每 1–4 小时一次）的健康快照检查，或完全交由看板观察、按需唤醒。

---

## 二、Step 2：在线实验“只读诊断红线”与三类异常分级处置

### 🚨 在线实验“只读诊断红线”（Inspect-Only Live Experiment Rule — 最高铁律）
当正式队列正在远端运行时，若用户发消息询问状态（例如*“看下怎么回事，某个批次好像跑得有点久”*）：
1. **默认仅拥有 100% 只读检查权限**！只能调用 `remote_gpu.py status`、`remote_gpu.py profile`、`exp_dashboard.py --once` 或只读查看远端日志定位原因，然后向用户清晰汇报实况（例如：“第 13 组某基线因某算子在 CPU 执行预计还需 X 分钟，未死锁；可选方案 A 继续等跑完，方案 B 暂停优化该算子后重跑该组”）；
2. **未经用户明确下达修改/重启指令，绝对禁止私自修改实验代码、绝对禁止执行 `remote_gpu.py kill` 杀掉正在跑的实验进程或擅自重启队列！**

---

### 获批介入后的三类故障分级处置与版本隔离

当运行确实发生故障中断（或经用户明确批准介入修复）时，严格按三类边界处置：

1. **Ⅰ 类：基础设施与物理资源中断**（SSH 断连、抢占实例重启、网络限流）
   - 保持代码零改动，直接重跑同一 `run_matrix.py run` 命令自动跳过已完成单元无缝续接。
2. **Ⅱ 类：代码实现 Bug 或算子性能修复**
   - 在本地修复后必须重过 `test_claims.py`（遵守 Stage 7A 防“改 A 坏 B”三项回归锁）；
   - **防跨版本混算铁律**：`ledger.jsonl` 只增不删！若修改了公共模块，必须对所有受影响的旧结果执行 `python scripts/run_matrix.py invalidate --ledger ... --pattern "<正则>" --reason "<原因>"` 标记失效后重跑；若仅单改了某个尚未跑完的独立基线文件且完全不影响已完成的无关联条件，经核实后可将新旧 commit 列入 `exp_manifest.json` 的 `compatible_commits`。
3. **Ⅲ 类：真实科学负结果或消融反转**
   - **严禁静默删减失败的数据集/种子、暗调 Baseline 或私自删改主方法组件**！完整保留正负结果在 `07_exp_results.md` 中如实报告，涉及主线简化或收缩 Claim 边界一律交由人类研究者拍板。

---

## 三、Step 3：确定性实验图表渲染与 `audit_exp.py` 保真交付

全部计划条件完成并通过 `remote_gpu.py pull` 拉回本地 `workspaces/<project>/experiments/results/` 后：

1. **渲染确定性实验图表与汇总表**：
   - 对照 `figures/figure_plan.md` 运行 `experiments/plots/plot_*.py`（直接读取 `results/` 原始数据文件，零硬编码数字），导出统一配色的矢量 `.pdf` + `300 DPI .png` 至 `workspaces/<project>/figures/`，并回填 `figures/figure_plan.md` 实测观察结论。
2. **撰写 `07_exp_results.md` 并执行强制确定性审计**：
   - 按 `templates/07_exp_results.md` 撰写结果报告（核心数值附 `<!-- @evidence:experiments/results/...#key -->` 溯源标签），运行并确保零阻断报错通过：
     ```bash
     python scripts/audit_exp.py \
       --manifest workspaces/<project>/experiments/exp_manifest.json \
       --ledger workspaces/<project>/experiments/results/ledger.jsonl \
       --plots-dir workspaces/<project>/experiments/plots \
       --figures-dir workspaces/<project>/figures \
       --results-md workspaces/<project>/07_exp_results.md \
       --out workspaces/<project>/experiments/results/audit_report.md
     ```
   - 对 `INVESTIGATE_IDENTICAL_METRICS` 告警逐一核实原因并在报告中交代，确认 `PASS` 后向用户交付完整实验结果与图表包。
