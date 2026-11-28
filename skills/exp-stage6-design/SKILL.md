---
name: exp-stage6-design
description: Stage 6 of ResearchFlow Experimentation. Reads back Stage 1-5 domain benchmark conventions, designs a subfield-authentic full experiment plan and data-figure blueprint (separating GPU runs from zero-GPU derived slices), estimates GPU-hours from Gate 0 telemetry, and pauses to negotiate compute & seeds with the user before locking exp_manifest.json.
---

# Stage 6 — 子领域惯例驱动的实验与数据图表设计 (`exp-stage6-design`)

实验设计是整篇论文成败的分水岭。本技能在 `05_pilot_report.md` 锁定真实有效方法后，**先不向算力做玩具化妥协**，而是立足 Stage 1–5 已沉淀的本方向顶会文献证据，设计出一份**符合子领域审稿标准、逻辑严密、最大化“一跑多切”**的完整实验与数据图表蓝图（`06_exp_plan.md` + `figures/figure_plan.md`），附带精确算力耗时估算单后**停下来与人类研究者协商拍板**。

---

## 一、Step 1：强制回读前序产物，提炼《子领域顶会实验惯例参照》

严禁脱离本子领域文献凭空套用千篇一律的死板模板！动笔前**必须依次回读以下已归档产物**：
1. **`02_paper_map.md` 第 5 节《小方向主实验共识统计》**：提取前期统计的高频通用 Benchmarks、数据划分、主评价指标及常规 Baseline 构成与数量；
2. **`04_handoff.md` 第 4–5 节《主实验文献共识设置与风险混杂项》** 与 **`05_pilot_report.md`**（锁定后的方法精确规格 + `Gate 0` 真机实测的 `ms/step` 与 `peak_vram_gb`）；
3. **3–5 篇最近邻顶会论文（含 `Direct Baseline` 与最新 `Recent Frontier`）的 `papers/<slug>/notes.md` 第 4、6 节及 `papers/<slug>/index.md` 第 3 节（Experimental & Summary Tables）**：必要时按行号区间回读 `source/` 原文实验章节，摸清本方向顶会论文真实的“证据长相”：
   - **主表常规配置**：同行普遍测几个 Benchmark、什么规模的模型底座、对比几个 Baseline？**同行惯例是汇报固定单一种子（`1 seed`，大模型/3DGS/Agent 极常见）还是多种子/多序列均值±标准差（`3–5 seeds`）？**
   - **超参公平协议**：同行采用哪种协议？（`Paper-Native` 沿用各方法官方最优超参 / `Common Protocol` 统一公共超参 / `Equal-Tuning` 同等验证集搜索预算）
   - **辅助实验与图表分布**：同行通常靠哪 2–3 类机制实验、敏感度分析和什么类型的实验图把论文故事撑满？

将上述归纳写入 `06_exp_plan.md` 第 1 节，作为整份实验设计的客观标尺。

---

## 二、Step 2：围绕科学主张弹性组合实验，严格区分“独立跑卡”与“零算力切片”

1. **以问题驱动按需设计（参考以下常见证据角色，作为启发式建议而非硬性凑数指标）**：
   - *核心主表对决（Main Comparison）*：在公认 Benchmark 上对比经典基线、`Baseline-Clean`（修复前人代码缺陷/对齐底座）、近 1 年最新竞争方法与我方方法，同时汇报主指标与**权衡对偶指标**（如准确率 vs. Token 开销、抗遗忘 `BWT` vs. 新任务可塑性 `FWT`、压缩率 vs. PSNR/FPS）；
   - *去混杂与反事实消融（Ablations & Counter-Variants）*：当核心方法很精炼（仅 1–2 个原语）时，不要硬凑模块做减法，可通过**设计选择替换**（如近似算子 vs. 精确算子）或**等预算/等参数反事实变体**（排除参数量、步长范数等混杂解释）来证明核心机制的因果贡献；
   - *内部机制诊断（Mechanism Diagnostics）*：验证方法内部几何/统计中间量确实符合理论预期（优先复用 `Gate 0` 动机探针或主实验顺手落盘的数据）；
   - *超参敏感度、鲁棒性与全口径工程开销（Sensitivity, Robustness & Overhead）*：新引入超参的一维权衡曲线、场景/规模鲁棒性，以及理论复杂度 + 实测耗时/峰值显存/存储开销表。
2. **显式拆分两张表，最大化“一次运行落盘，多维图表切片”（Log Once, Slice Many）**：
   - **表 A — 实际需跑卡的独立运行批次（`Execution Runs`）**：真正消耗 GPU/API 预算的实验组；
   - **表 B — 零额外算力的派生分析与图表切片（`Derived Views`）**：明确要求在跑表 A 时顺手落盘细粒度中间文件（如完整逐任务评测矩阵、逐样本预测与长度、逐层谱/激活统计、峰值显存与单步耗时），事后直接用脚本切出多张机制图、权衡图与开销表，避免重复烧卡。
3. **三层参数公平架构（防“一刀切同学习率”误伤基线）**：
   - **① 全局公平协议**（全方法强制共享）：数据划分、评测器与指标口径、任务序列、训练轮数/样本预算；
   - **② 方法级科学配置**（按选定的 `Paper-Native` / `Equal-Tuning` / `Common` 协议提前声明并冻结）：各方法自身的官方推荐学习率、正则系数与特有超参（严禁在测试集上调参）；
   - **③ 物理执行旋钮**（允许在满足条件等价前提下适配显存）：`micro_batch_size` + `grad_accum_steps`、缓存路径、工作线程数。

---

## 三、Step 3：只规划“实验数据图表”，输出 `figures/figure_plan.md` 双轨说明书

1. **职责边界**：本阶段与 Stage 7B **仅负责定量/定性实验数据相关的图表与结果表格**；论文概念示意图与模型架构框图一律留到后续“论文撰写阶段”再设计。
2. **必交说明书 `workspaces/<project>/figures/figure_plan.md`**（参照 `templates/figure_plan.md`）：
   - 逐一说明论文实验部分建议在哪个位置放什么图/表、支撑哪条核心 Claim、**精确绑定表 A/B 落盘的哪个结果文件与字段名**、横纵轴与分组定义，以及单栏/双栏排版建议；
   - 该文件既是 Stage 7B 编写 `plots/plot_*.py` 自动出图的精确规格书，也是兼容无作图能力宿主或供人类后续与 Agent 交互微调重绘的独立指南。

---

## 四、Step 4：声明机制触发测试 + 算力耗时账单，停顿协商（⏸️ 强制停顿节点）

1. **前置声明 3–5 条“机制感知最小触发断言”（供 Stage 7A 编写 `tests/test_claims.py`）**：
   - 针对方法类型声明真正有效的触发检验（如：修改 Loss/优化器查单步参数更新或梯度分量；持续学习构造第 2 任务非空历史子空间 $U$ 查 $\|U^\top g\|_2 \le \epsilon$；推理/Agent 查路由或停时状态转移），避免在 Stage 7A 用死板的“前两步前向输出不同”误杀正确实现。
2. **基于 `Gate 0` 实测数据的算力与墙钟时间估算表**：
   - 利用 `05_pilot_report.md` 实测的 `ms/step` 与显存，折算出满配方案在常见卡型（如 `1× 4090`、`4× 4090` 多卡并行、`1× A100-80G`）上的预估总卡时与墙钟时长，并直观列出可协商弹性项（如主表/消融采用 `1 seed` 还是 `3 seeds` 的耗时差、次要底座开销）。
3. **强制停顿与协商锁定**：
   - 向用户呈现 `06_exp_plan.md` 与 `figures/figure_plan.md`，沟通接下来可调配的机器规格/SSH（除非此前已明确指定且预算充裕）及是否需要调整种子数或扩展批次；
   - **经用户确认拍板后**，将最终商定的实验矩阵固化生成 `workspaces/<project>/experiments/exp_manifest.json`，交接进入 Stage 7A。
