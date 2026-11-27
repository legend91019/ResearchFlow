---
name: idea-stage4-review-handoff
description: Stage 4 of ResearchFlow Ideation. Launches a history-isolated Critical Reviewer subagent for minimum-novel-core peeling, L2 theorem/appendix scoop checks, elementary dominance tests, and coupled state-machine numerical simulations, then exports a Pilot-First (Gate 0 + Main Table) 04_handoff.md.
---

# Stage 4 — 独立反证审查与先导优先交接导出 (`idea-stage4-review-handoff`)

参与多轮讨论的主 Agent 不可避免带有确认偏误（Confirmation Bias）与“补丁叠床架屋”倾向。在正式投入算力进入“实验设计”阶段前，本技能通过**单个零历史包袱的 `Critical Reviewer Subagent`** 执行严苛的**最小创新核剥离、源码级查重、初等占优检验与跨模块级联数值反证**，通过后导出包含 **`Gate 0` 最小生死先导实验** 与 **文献共识主实验** 的 `04_handoff.md`。

> **核心原则**：不做虚头巴脑的“7.2/10 算命打分”，也不堆砌多个审稿 Agent 制造官僚噪音；只做能揪出真实硬伤的**减法剥离、原文附录核对与端到端级联仿真**。

---

## 一、Step 1：启动隔离的 `Critical Reviewer Subagent`

派生一个**全新的历史隔离 Subagent**（如 Antigravity 的 `invoke_subagent(TypeName="self")` 或 Claude Code 的 `Task`）。

### 信息隔离要求（防确认偏误与防“只核销旧清单”）
- **只允许提供给 Reviewer 的材料**：
  1. `01_scope.md` 中的算力边界与时间截断约束（若处于 `--before-date YYYY-MM-DD` 历史回测模式，Reviewer 的所有网页检索、`--arxiv-recent`、`--scan-bib` 与 `cite_graph.py` 必须严格截断在该日期之前，严禁检索或引用截断日及之后的文献）；
  2. `03_idea_discussion.md` 中“当前研究问题”、“已验证事实”、“当前工作假设”与“当前候选 Idea”四个客观段落；
  3. `02_paper_map.md` 及 `papers/<slug>/` 下的 `notes.md`、`index.md`、`source/` 与 `repo/` 路径。
- **严禁传入**：此前主对话里的妥协话术；**若为返修后的第 2 轮复审，严禁让 Reviewer 仅做“首轮问题核销验收”**——Reviewer 必须把返修后的完整方案当作全新投稿，从第一性原理重新执行下方全部五项核查！

### Reviewer 必须独立完成的五把手术刀核查（写入 `search_logs/critical_review.md`）

1. **最小创新核剥离与 `L2` 源码级撞车核查（Minimum Novel Core & L2 Scoop Check）**
   - **多路去包装检索**：抛开候选方案的自创缩写名（**严禁把业务词与自创算子名绑死在同一条高约束查询里**），分别执行：① `python scripts/cite_graph.py --arxiv-recent "<核心任务词>" --days 30` 扫最近零延迟预印本；② `python scripts/cite_graph.py --scan-bib workspaces/<project>` 扫本地二跳共引；③ 针对方案中每个核心算子（含返修新增机制）在 arXiv 与 **`OpenReview`（含 Workshop）** 独立检索。
   - **高危近邻强制升 `L2`**：凡搜到问题或机制高度相近的论文，**严禁仅读 `L0` 摘要就轻率下结论“不撞车”**！必须调用 `fetch_paper.py` 解包查看其正文定理/命题与 **Appendix 中的推导和受控实验表**（核查是否已在附录导出相同理论界或做过相同干预实验）。
   - **最小创新核五问（防组合唯一性陷阱）**：不能因为“没有单篇论文同时包含模块 A+B+C+D”就判新颖！必须先剥掉借用的统计外壳（如 `LTT / Pareto Testing`）、通用预处理和前人代码修复，明确回答：**“剩下的单一核心机制或科学发现是什么？能否由已有 2–3 篇论文平凡组合替代？是否患上了‘4 个缺陷拼 4 个补丁’的缝合症？”**

2. **核心前提真伪与反稻草人核查（Premise & Anti-Strawman Audit）**
   - 核查 `Direct Baseline` 及关键近邻的 `source/`、`repo/` 与 `notes.md`：① 声称要修的前人缺陷是否真实存在？② `03_idea_discussion.md` 对竞争方法（如已有兼容筛选或正则的近邻）是否存在“稻草人化矮化表述”？③ 代理指标与真实目标之间是否存在致命断层（如“动作改变 $\neq$ 错误修复”、“单步提示去记忆 $\neq$ 历史环境状态未污染”、“中心值守恒 $\neq$ 二维面积积分守恒”）？

3. **奥卡姆初等基线占优与平庸替代解释（Elementary Dominance & Simpler Alternative）**
   - **锤子找钉子检验**：对于方案引入的任何复杂数学形式（如赌博超鞅、高阶矩阵范数、多超参分段公式），检查在相同停时/约束条件下，**是否存在 1–2 行初等闭式方法（如精确超几何零失败检验、单步逻辑回归对数似然比、常数阻尼、等范数缩放）在数学上等价甚至统计功效更高**？若是，必须要求砍掉复杂包装！
   - **混杂控制检验**：若指标上涨，是否可能仅源于更新步长缩小、保护维数变大、牺牲新任务可塑性（未控 `Iso-Plasticity`）或探测预算不同？

4. **端到端级联状态机与极限反例数值仿真（Coupled Simulation — 必写 Python 脚本验算）**
   - **严禁将各子模块拆成孤岛分别喂理想 i.i.d. 随机数！** Reviewer 必须编写并运行简短 Python 脚本，将上下游模块串成**完整级联系统**测试：
     - *条件分布偏移*：上游门控/筛选放行后，下游统计量的条件期望性质（如 $\mathbb{E}[\text{drift} \mid \text{Healthy}, \text{Gate}=1] < 0$）是否依然成立？
     - *部分可观测与缺失反馈*：稀疏抽检未观测步（如 `80%` 未回读步）的赋值是否导致累积器产生负漂移死锁？
     - *多分支竞争与存活耦合*：上下界检测器在极端输入（如高置信错解复读）下是否发生抢跑冲突？全局 Top-$K$ 截断是否会误删供体所绑定的接收器根？
     - *解析极限与穷举真值表*：对小规模组合逻辑（如 3 规则全部单调布尔函数）或双图元重合积分做精确数值验算，排查漏项（如协方差偏移外积缺失）与 `NaN`/梯度退化。

5. **统计协议严谨性与先导实验可证伪性（Statistical Rigor & Pilot Falsifiability）**
   - 检查训练/校准/测试集划分是否真正满足统计检验前提（严格区分**真同分布可交换 `IID` 划分**与**无重叠但异构混合的 `OOD` 划分**；检查同题多采样非独立性及低准确率基率对总体风险分母的稀释，必要时要求同步约束条件风险）；
   - 检查是否能在用户的算力边界内设计出 **1–3 小时即可证伪核心假设的最小先导实验（`Gate 0`）**。

### 审查定性裁决（四选一，拒绝虚假“100% 完美 PASS”）
- **`READY_FOR_PILOT`**：单一核心机制清晰、无直接撞车、通过初等占优与端到端级联数值验证，准予移交先导实验（但仍须如实列出尚未经真实数据证实的核心经验假设）；
- **`NEEDS_SIMPLIFICATION`**：科学问题有价值，但存在多模块拼盘堆砌、复杂数学包装被初等方法占优或手工魔数过多，**必须退回 Stage 3 做减法瘦身后再审**（严禁靠继续加补丁应付！）；
- **`NEEDS_EVIDENCE`**：存在未升档至 `L2` 核清的近邻工作、跨模块级联耦合漏洞或公式缺项，需补查/修正后再审；
- **`FATAL_FLAW`**：核心科学贡献已被既有论文正面覆盖，或核心前提在原代码/数学反例下根本不成立，建议退回 Stage 3 执行 `Pivot`。

---

## 二、Step 2：与研究者诚实复盘并执行反向补丁校验

1. 主 Agent 读取 `search_logs/critical_review.md`，不加粉饰地向用户同步审查发现：
   - 若为 `NEEDS_SIMPLIFICATION`：必须**砍掉外围冗余模块与花哨包装**，聚焦单一核心机制，绝不允许再叠新模块；
   - 若为 `FATAL_FLAW` 或 `NEEDS_EVIDENCE`：按 `Challenge / Pivot` 流程回退 Stage 3 补证或重构。
2. **尾轮修改反向自检铁律**：在将 Reviewer 的任何实验或公式修改建议合入最终 `04_handoff.md` 之前，主 Agent 必须核验该修改本身是否满足统计前提（如真 `IID` 可交换性）与跨模块兼容性，严禁不经核查盲目照抄审稿人顺手写的规避补丁。

---

## 三、Step 3：导出“先导优先”两级实验接力包（`04_handoff.md`）

参照 `templates/04_handoff.md`，结合 `02_paper_map.md`、`03_idea_discussion.md` 与 `critical_review.md` 生成 `workspaces/<project>/04_handoff.md`：

1. **多维就绪度诚实声明（Readiness Matrix）**：分别标明 `数学与级联数值自洽性`、`文献新颖性边界`、`工程与算力准备度` 及 **`核心经验假设状态（待 Gate 0 先导实证）`**，严禁在跑真实实验前宣称“全部风险 100% 根除”。
2. **方法规格与基线分离**：清晰区分“公平对齐基线纠偏（Clean Baseline Fixes）”与“本文核心机制改动”，附精确 `papers/<slug>/repo/`（含 commit SHA）文件与行号坐标。
3. **两级实验漏斗（先 `Gate 0` 生死验证，后 `Main Table` 全面铺开）**：
   - **第一级：`Gate 0` — 最小可行证伪先导实验（Pilot Falsification Test，单卡 1–3 小时可完结）**：在不开发重型底层算子、不跑十几个基线的前提下，用最小代表性模型/合成基准直接检验整篇方案最核心的 1–2 个未验证假设（如代理损失与真值负迁移的 AUROC、级联门控下的真实漂移方向、0 步微调积分误差），并给出明确的 **Go / No-Go 量化决策阈值**；
   - **第二级：主实验（Main Table）文献共识设置（仅在 `Gate 0` 通过后启动）**：严格依据 `02_paper_map.md` 中近期论文主表给出公认 Benchmarks、主指标（含条件风险/等可塑性/全口径成本指标）与必比 Baseline 阵容（经典奠基 + 1–3 篇同底座公平靶子 + 近 1 年最新前沿）。
