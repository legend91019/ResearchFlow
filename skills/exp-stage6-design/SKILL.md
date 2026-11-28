---
name: exp-stage6-design
description: Stage 6 of ResearchFlow Experimentation. Dispatches an Experiment Setup Auditor Subagent to verify peer experimental conventions from .tex/repos, designs a clear subfield-authentic experiment and data-figure plan (separating GPU runs from zero-GPU derived slices), provides optional on-demand time estimation, and pauses to align compute & scope with the user.
---

# Stage 6 — 文献实证审计驱动的实验与数据图表设计 (`exp-stage6-design`)

实验设计是整篇论文成败的分水岭。注意：前序 `02_paper_map.md` 第 5 节与 `04_handoff.md` 第 4 节留下的只是实验设置的**高层目录/摘要**——若主窗口不核查原论文细节就直接拍脑袋排矩阵，极易漏看同行算力前提、混写样本规模或排出无法落地的交叉乘积。

因此，本技能先通过**独立的 `Experiment Setup Auditor Subagent` 产出一份《前人实验设置核查报告》**，再由主 Agent 按图索骥设计可读性强、最大化“一跑多切”的实验与数据图表蓝图（`06_exp_plan.md` + `figures/figure_plan.md`），并在与人类研究者协商拍板后锁定执行范围。

---

## 一、Step 1：派发 `Experiment Setup Auditor Subagent` 产出真实实验惯例报告

主 Agent **严禁在主窗口直接通读多篇论文长文或凭记忆猜测实验参数**！读取 `02_paper_map.md`（§5）、`04_handoff.md`（§4–5）与 `05_pilot_report.md` 作为导航索引后，派生一个隔离的 **`Experiment Setup Auditor Subagent`**（如 `invoke_subagent(TypeName="self")` 或 `Task`），专门核查 3–5 篇最近邻锚点论文的 `papers/<slug>/notes.md`（§4、§6）、`index.md`（§3 实验表索引）、`source/*.tex`（实验节与附录 Implementation Details）及 `repo/` 官方运行脚本，输出 **`workspaces/<project>/search_logs/stage6_exp_conventions.md`**：

1. **精确数据集与样本规模核实**：每篇同行实际跑的是全量数据还是官方轻量/子采样赛道（如 `29k` vs. `1k/task`、`TRACE_5000` vs. `TRACE_1000`）？各子任务的训练轮数、序列长度、提示词模板及**已验证的本地/官方获取路径**（优先标明已在 `papers/<slug>/repo/` 中现成存在的数据文件，严禁凭空猜测 HuggingFace 仓库名）。
2. **同行算力前提与规模对标**：核查每篇论文跑主表实际动用了什么硬件（如 `8× H100` 还是单张 `24GB/48GB` 卡），以及中小算力论文在模型大小或数据子集上的真实取舍惯例。
3. **多模型底座分工惯例**：核查同行是如何在主模型与副模型之间分工的（顶会惯例通常是**主力模型跑全套主表+消融+敏感度，副模型仅跑 1 张跨架构或跨规模验证表**，绝不做全矩阵死板交叉乘积）。
4. **种子数、评测频率与超参公平协议**：同行汇报固定单一种子（`1 seed`）还是多种子/多序列（`3–5 seeds`）？过程评测是测完整矩阵还是仅测对角线+末行（及对应的指标精确公式）？采用 `Paper-Native`（官方推荐超参）、`Equal-Tuning`（同验证集搜索预算）还是 `Common Protocol`？
5. **同行辅助实验与实验图形态分布**：同行除主表外普遍配哪 2–3 类诊断/敏感度/开销实验与图表类型来支撑完整叙事。

---

## 二、Step 2：按图索骥设计实验蓝图（清晰可读 + 弹性组合 + 一跑多切）

主 Agent 仅读取落盘后的 `stage6_exp_conventions.md` 与 `05_pilot_report.md`，参照 `templates/06_exp_plan.md` 撰写 `06_exp_plan.md`：

1. **面向研究者的清晰白话导读（拒绝堆砌晦涩内部代号）**：
   - 在列运行批次表之前，必须先用简练直观的语言向研究者讲清楚：**每个选定 Benchmark 具体考什么任务机制（含轮数、特殊附加评测如合并后通用能力测试的物理意义）**，以及**每个批次各自承担什么独特职责**（例如清晰区分“只跑几十步做显存/延迟体检的批次”与“跑完整轮数考准确率的批次”，让人一眼看懂不混淆）。
2. **以科学主张驱动弹性组合（不硬凑固定模块配额，避免无意义交叉乘积）**：
   - 参考本方向顶会惯例按需组合证据角色：核心主表对比（同时汇报主指标与权衡对偶指标）、去混杂/等预算反事实消融（含 `Baseline-Clean` 剥离）、内部机制诊断、核心超参敏感度/规模扩展、以及全口径计算/显存/存储开销对比；
   - **显式拆分两张表，最大化“一次运行落盘，多维图表切片”（Log Once, Slice Many）**：
     - **表 A — 实际需跑卡的独立运行批次（`Execution Runs`）**：真正消耗算力的实验组；
     - **表 B — 零额外算力的派生分析与图表切片（`Derived Views`）**：明确指定跑表 A 时顺手落盘哪些细粒度文件（如评测矩阵、逐层统计、步耗时与峰值显存），事后零算力切出多张机制图与分析表。
3. **三层参数公平架构**：
   - **① 全局公平协议**（全方法共享）：数据划分、只读评测器与指标定义（注意：若部分方法采用精简评测频率如 `diag_last`，全图全表对比指标必须采用数学上严格同口径的定义！）、训练预算；
   - **② 方法级科学配置**（按选定公平协议声明各方法超参来源，严禁在测试集上调参）；
   - **③ 物理执行旋钮**（允许在满足条件等价前提下适配显存）。

---

## 三、Step 3：只规划“实验数据图表”，输出 `figures/figure_plan.md` 双轨说明书

1. **职责边界**：本阶段与 Stage 7B **仅负责定量/定性实验数据相关的表格与图表**；论文整体概念图与模型架构框图一律留到后续“论文撰写阶段”再设计。
2. **必交说明书 `workspaces/<project>/figures/figure_plan.md`**（参照 `templates/figure_plan.md`）：
   - 逐张写明建议放置位置、核心论证目的、**精确绑定的 `results/` 数据文件路径与字段名**、横纵轴/分组定义与单双栏建议；兼作 Stage 7B `plots/plot_*.py` 规格书与无作图能力宿主/人工交互重绘指南。

---

## 四、Step 4：机制触发断言、按需时间估算与停顿协商（⏸️ 强制停顿节点）

1. **前置声明 3–5 条“机制感知最小触发断言”（供 Stage 7A 编写 `tests/test_claims.py`）**：
   - 按方法机制类型定义有效触发检验（如非空历史子空间投影残差、单步更新方向、真实样本字典格式与异常降批自愈断言）。
2. **耗时估算（可选 — 仅在用户有硬租期限制或主动要求估时时执行）**：
   - 时间估算**不是必选动作**（开放式实验室服务器或短实验无需折腾复杂估时）；
   - **若用户明确提出时间预算限制或要求估算耗时**，切记四条实战经验：① 核准 `Gate 0` 实测吞吐对应的真实 `effective_batch_size` 与序列长度，**严禁拿显卡纸面峰值 TFLOPS 拍脑袋乘系数**（LLM 训练与长生成往往卡在显存带宽而非算力）；② **必须把非主干训练开销算进总账**：$O(T^2)$ 全矩阵评测 vs. 末行评测次数、学习率网格校准总次数、重型 Baseline 的任务间分解/Fisher 算子耗时、以及大断点写盘 I/O；③ 在未连上目标真机前仅给出参照同行卡时的粗估区间，待 Stage 7A 连上目标卡跑完 2 步全方法微基准后再核准精确总账；④ 预留至少 `15%–20%` 安全余量（或划分 `P1 核心必保` 与 `P2 富裕扩展` 优先级）。
3. **强制停顿与协商锁定**：
   - 向用户清晰汇报 `06_exp_plan.md` 与 `figures/figure_plan.md`，沟通拟投入的计算资源（除非此前已明确锁定）及种子数/模型规模/数据集赛道取舍；
   - **经用户拍板后**，固化生成 `workspaces/<project>/experiments/exp_manifest.json`，建议用户执行 `/compact` 或开新窗口进入 **Stage 7A（`skills/exp-stage7a-coding/SKILL.md`）**，保持编码阶段上下文清爽。
