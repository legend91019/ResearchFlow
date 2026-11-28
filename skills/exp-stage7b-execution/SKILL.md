---
name: exp-stage7b-execution
description: Stage 7B of ResearchFlow Experimentation. Runs multi-GPU/remote queues via remote_gpu.py and run_matrix.py with append-only ledger tracking, applies 3-class failure triage without silent cherry-picking, renders deterministic data figures, and runs audit_exp.py before delivering 07_exp_results.md.
---

# Stage 7B — 多卡/远程断点执行、分级自愈与实验图表审计 (`exp-stage7b-execution`)

本技能承接通过三重预检门禁的 `experiments/` 代码与 `exp_manifest.json`，负责**稳健调度单卡/多卡远程算力、按科学权限边界处理运行故障、在数据跑完后直接生成确定性实验图表并执行七维保真审计**，最终交付完全可溯源的 `07_exp_results.md`。

> **核心原则**：Agent 拥有充分的**工程排障自主权**，但绝不拥有未经授权的**科学篡改权**——严禁为了迎合预期结论而私自删条件、挑种子、混算不兼容代码版本或静默改动方法核心。

---

## 一、Step 1：多卡并发守护启动与非轮询状态巡检

1. **同步脚本与后台队列启动**：
   将 `scripts/run_matrix.py` 一并推入实验目录，通过 `remote_gpu.py launch` 在远端挂起单卡或多卡并发运行队列（`--gpus 0,1,2,3` 会自动开启工作池将独立 `condition_id` 动态负载均衡到各张空闲显卡；纯 API/CPU 实验可用 `--workers N`）：
   ```bash
   python scripts/remote_gpu.py push --workspace workspaces/<project> --src experiments
   python scripts/remote_gpu.py push --workspace workspaces/<project> --src ../../scripts/run_matrix.py --dest experiments/run_matrix.py
   python scripts/remote_gpu.py launch --workspace workspaces/<project> --job-id main_exp --workdir experiments \
     --cmd "python run_matrix.py run --manifest exp_manifest.json --ledger results/ledger.jsonl --gpus 0 --commit $(git rev-parse --short=12 HEAD)"
   ```
   - `run_matrix.py` 采用**只增不删（Append-Only）**的 `results/ledger.jsonl` 账本，每完成一个单元立即 `fsync` 落盘并原子刷新 `results/progress.json`；任何中断重连后再次启动同一命令，会自动跳过已有效 `completed` 的条件。
2. **定时非轮询巡检**：
   - 使用宿主定时唤醒工具（按总预计时长每 15–45 分钟检查一次），调用单次快照命令：
     ```bash
     python scripts/remote_gpu.py status --workspace workspaces/<project> --job-id main_exp --progress-file experiments/results/progress.json
     ```
   - 注意：`LOW_GPU_UTIL`（GPU 利用率 `<5%`）仅作为**诊断信号**而非自动判死（API 型评测、CPU 预处理或任务切换间隙本就低占用；仅当进度长期停滞时才调用 `remote_gpu.py profile` 抓栈排查死锁或慢算子）。

---

## 二、Step 2：异常与结果的“三类分级自愈”及版本隔离铁律

巡检中遇到报错、中断或非预期数值时，严格按以下三类定性处置：

1. **Ⅰ 类：基础设施与物理资源故障**（SSH 闪断、实例抢占重启、磁盘空间告警、下载限流、突发显存峰值）
   - **处置**：清理缓存或应用经 Stage 7A 条件等价验证的物理参数（或开启梯度检查点），直接重新拉起 `run_matrix.py run` 从断点续跑，**零算法代码修改**。
2. **Ⅱ 类：代码实现 Bug**（特定数据集边界维度报错、数值溢出 `NaN`、某 Baseline 参数传错）
   - **处置与版本防混算铁律**：
     1. 在本地修复 Bug 并重新运行通过 `experiments/tests/test_claims.py`；
     2. **严禁直接删除 `ledger.jsonl` 历史行，也严禁将含公共 Bug 的旧版本结果与新版本结果直接混算**！必须评估该修改的影响范围：若修改了公共模块（如数据预处理、公共训练循环），对所有受影响的已完成条件执行失效标记：
        ```bash
        python scripts/run_matrix.py invalidate --ledger workspaces/<project>/experiments/results/ledger.jsonl \
          --pattern "<受影响条件正则>" --reason "<说明修复的公共Bug及影响范围>"
        ```
        若仅修改了纯注释/日志且完全不影响数值兼容性，方可将新旧 commit 显式列入 `exp_manifest.json` 的 `compatible_commits`；
     3. 同步新代码并重跑被标记 `invalidated` 与 `failed` 的条件。
3. **Ⅲ 类：真实科学负结果或消融反转**（代码运行完全正常，但某条件下我方未超最强基线，或消融中更简变体反而优于完整版）
   - **处置**：**严禁静默删减失败的数据集/种子、严禁暗中调弱 Baseline、严禁未经用户批准擅自删改主方法组件重新包装**！保留完整账本与全部正负数据：若核心主表全面不成立，暂停向用户汇报并讨论回退/转型；若局部边界受限或某次要项多余，在 `07_exp_results.md` 中完整呈现并向用户提出公开简化或收缩 Claim 边界的建议。

---

## 三、Step 3：确定性实验图表渲染与 `audit_exp.py` 保真审计

全部计划运行落盘并通过 `remote_gpu.py pull` 拉回本地 `workspaces/<project>/experiments/results/` 后：

1. **生成确定性实验数据图表与汇总表**：
   - 对照 `figures/figure_plan.md` 编写并运行 `experiments/plots/plot_*.py`（以及必要的表格聚合脚本）：**脚本必须直接读取 `results/` 下的原始 JSON/CSV/NPZ 数据动态计算均值、标准差与指标，严禁在绘图代码中硬编码任何实验结果浮点数**；
   - 统一全套图表的方法配色与命名，双格式导出矢量 `.pdf`（供论文排版直接引用）与高分辨率 `.png`（供视觉检查无文字重叠、无边界裁切、字号清晰）至 `workspaces/<project>/figures/`，并同步更新 `figures/figure_plan.md` 中的实际生成文件路径与关键视觉结论。
2. **撰写 `07_exp_results.md` 并执行强制确定性审计**：
   - 按 `templates/07_exp_results.md` 撰写完整实验报告（核心主表数值建议附 `<!-- @evidence:experiments/results/...#key -->` 溯源注释）；
   - **交付前必须运行并全绿通过**：
     ```bash
     python scripts/audit_exp.py \
       --manifest workspaces/<project>/experiments/exp_manifest.json \
       --ledger workspaces/<project>/experiments/results/ledger.jsonl \
       --plots-dir workspaces/<project>/experiments/plots \
       --figures-dir workspaces/<project>/figures \
       --results-md workspaces/<project>/07_exp_results.md \
       --out workspaces/<project>/experiments/results/audit_report.md
     ```
   - 若审计提示 `INVESTIGATE_IDENTICAL_METRICS`（两个条件指标完全一致），必须核实到底是消融开关未接通还是该组件确实零影响，并在报告中如实交代；确保 `Blocking Errors` 清零后，向用户交付 `07_exp_results.md` 与 `figures/` 图表成果。
