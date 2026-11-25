---
name: idea-stage4-review-handoff
description: Stage 4 of ResearchFlow Ideation. Launches a history-isolated Critical Reviewer subagent to challenge premises and check for recent scooping papers, then exports the finalized proposal and literature-grounded main experimental setup to 04_handoff.md.
---

# Stage 4 — 独立反证审查与主实验交接导出 (`idea-stage4-review-handoff`)

参与多轮讨论的主 Agent 不可避免带有确认偏误（Confirmation Bias）。在正式投入算力进入“实验设计”阶段前，本技能强制执行一次**历史隔离的独立反证与撞车核查**，通过后整理输出 `04_handoff.md`。

> **注意**：本阶段不做虚头巴脑的“7.5/10 算命式打分”，只做刀刀见血的**撞车检索、前提反证与可证伪性核查**。

---

## 一、Step 1：启动隔离的 `Critical Reviewer Subagent`

派生一个**全新的隔离 Subagent**（如 Antigravity 的 `self` 子智能体或 Claude Code 的 `Task` 子智能体）。

### 信息隔离要求（防确认偏误）
- **只允许提供给 Reviewer 的材料**：
  1. `03_idea_discussion.md` 中“当前研究问题”、“已验证事实”、“当前工作假设”与“当前候选 Idea”四个客观段落；
  2. 所依赖的 `Direct Baseline` 及关键相关论文在 `papers/<slug>/` 下的 `notes.md`、`index.md` 与 `source/`、`repo/` 路径。
- **严禁向 Reviewer 传入**：此前主对话里双方的妥协过程、说服话术或主观偏好。

### Reviewer 必须独立完成的五项核查任务
要求 `Critical Reviewer Subagent` 扮演严苛、挑剔的顶会审稿人，独立执行检索与原文抽查，逐一回答以下 **五问** 并写入 `workspaces/<project>/search_logs/critical_review.md`：

1. **撞车与最近邻核查（Scoop Check）**
   - 抛开候选方案自创的包装名词，将核心技术操作拆解为多组同义术语（含相邻子领域叫法），使用宿主 Web Search（重点覆盖近 6–12 个月 arXiv 与 OpenReview）及 `cite_graph.py` 独立检索：**是否已有论文发表了实质相同的机制或得出了相同结论？** 若有高度近似工作，逐项对比问题、机制与适用条件。
2. **核心前提真伪核查（Premise Audit）**
   - 抽查候选方案所依赖的 `Direct Baseline` 原文（`source/`）与代码（`repo/`）：候选方案声称要解决的“前人缺陷”，在原始代码和实验表里**真的存在吗**？还是对前人论文的误读？
3. **平庸替代解释（Simpler Alternative Explanation）**
   - 如果按候选方案改完后指标上涨了，审稿人最容易提出什么**更简单平庸的替代解释**（例如：只是隐式降低了学习率、增加了可训练参数量/存储开销、变相做了权重衰减或集合平均）？需要在后续实验中锁死什么控制变量才能堵住这个质疑？
4. **实验可证伪性（Falsifiability）**
   - 在用户的算力边界（见 `01_scope.md`）内，主实验与关键对照实验能否真正验证或证伪核心假设？
5. **潜在翻车点预判（Failure Mode）**
   - 如果真实跑下来毫无增益甚至变差，从数学或优化机制上看最可能死在哪个环节？

### 审查定性结论（三选一）
- **`PASS`**：未发现直接撞车，核心前提有据可查，潜在混杂因素可通过明确对照实验控制；
- **`NEEDS_EVIDENCE`**：存在未核实的近邻工作威胁或关键原文/代码细节未查清，需补查后再议；
- **`FATAL_FLAW`**：发现直接撞车论文，或核心前提在原论文/原代码中不成立，建议退回阶段 3 重构或换思路。

---

## 二、Step 2：与研究者复盘审查结论

主 Agent 读取 `search_logs/critical_review.md`，如实、不加修饰地将 `Critical Reviewer` 找出的近似工作、尖锐质疑与混杂风险同步给用户：
- 若为 `FATAL_FLAW` 或 `NEEDS_EVIDENCE`：按 `Challenge` / `Pivot` 流程回到阶段 3 补查证据、修改方案或更换切入点；
- 若为 `PASS`（或用户审阅 `NEEDS_EVIDENCE` 后明确决定如何通过实验控制解决该疑点）：进入 Step 3 导出交接文档。

---

## 三、Step 3：导出主实验共识接力包（`04_handoff.md`）

参照 `templates/04_handoff.md`，结合 `02_paper_map.md`、`03_idea_discussion.md` 与 `critical_review.md` 生成最终的 `workspaces/<project>/04_handoff.md`：

1. **方法规格与源码坐标**：写清核心研究问题、相对 `Direct Baseline` 的精确公式改动、以及对应官方仓库（`papers/<slug>/repo/`，含 commit SHA）中待修改的具体文件与函数位置。
2. **主实验（Main Table）文献共识设置**：
   - **严禁拍脑袋编造实验设置**——直接依据 `02_paper_map.md` 中 1–3 篇 `Direct Baseline` 与 `Recent Frontier` 论文的实际主表，给出该小方向公认的 **Benchmarks、任务划分与主评价指标**；
   - **对齐近期顶会规模的必比 Baseline 名单**：参考近期同方向论文主表通常对比的方法数量，列出完整阵容——涵盖**经典奠基方法** + **1–3 篇直接靶子基线** + **近 1 年最新前沿方法**（保障审稿时效性）。
   - *边界说明*：本文件聚焦交付**主实验核心设置**与 **`Critical Reviewer` 提示必须严控的混杂变量/风险清单**；具体的消融矩阵、机制分析实验与图表规划留交下一大阶段（实验设计阶段）专门展开。
