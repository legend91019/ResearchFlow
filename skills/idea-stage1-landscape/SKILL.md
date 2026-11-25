---
name: idea-stage1-landscape
description: Stage 1 of ResearchFlow Ideation. Conducts survey-first broad landscape discovery for a research area, maps natural methodological taxonomy and temporal evolution, clarifies compute boundaries, and locks a sub-direction into 01_scope.md.
---

# Stage 1 — 方向广搜与细分线路锁定 (`idea-stage1-landscape`)

本技能用于课题起步阶段：将用户给出的宽泛研究方向（及算力/场景偏好）转化为**有真实文献支撑的领域分类树（Taxonomy）与演进轮廓**，协助用户选定具体研究枝杈并落盘 `01_scope.md`。

> **严禁事项**：在本阶段结束前，**严禁提出具体的新算法 Idea、严禁凭空钦定评测数据集、严禁预估涨点指标**。本阶段的唯一任务是摸清版图、铺垫概念、选准赛道。

---

## 一、双起点分流检查（Entry Check）

在启动大规模广搜前，先判断用户输入属于哪种起点：

1. **种子论文直入模式（Fast-Track）**
   - 若用户已明确给出 **1–3 篇核心种子论文**（arXiv ID / PDF / 标题）且研究子方向与算力边界清楚：
   - 无需铺开全领域泛搜。用 `python scripts/fetch_paper.py` 拉取种子论文源码与元数据，核对其引言与相关工作确认所属细分流派，与用户简要对齐后直接参照 `templates/01_scope.md` 写出 `workspaces/<project>/01_scope.md`，**直接进入阶段 2（读取 `skills/idea-stage2-literature-map/SKILL.md`）**。

2. **宽泛方向探索模式（Standard Landscape）**
   - 若用户给出的是大方向或模糊问题（如“具身智能长期记忆”、“持续学习”、“扩散模型推理加速”），按下方流程执行。

---

## 二、执行流程（隔离上下文广搜）

### Step 1：派发 `Survey Subagent` 执行“综述优先 + 近期补漏”调研
**不要在主对话窗口连续刷十几次原始网页搜索**。优先派生具备联网与文件写入能力的子智能体（如 Antigravity 的 `self` 子智能体或 Claude Code 的 `Task` 子智能体；若宿主不支持联网子智能体，则集中执行后提示用户 `/compact`），向其下达明确指令：

1. **优先搜寻高密度二手地图（Survey / Taxonomy / Awesome 聚合源）**
   - 检索该方向近 2–3 年的高质量综述论文（`Survey`, `Review`, `Taxonomy`, `Benchmark`）、顶会 Tutorial 以及 GitHub 高星 `Awesome-<Topic>` 仓库。
   - 若找到高度契合的近期 arXiv 综述论文，优先调用：
     ```bash
     python scripts/fetch_paper.py --arxiv <survey_arxiv_id> --workspace workspaces/<project> --slug survey_<short> --role Foundational
     ```
     通过生成的 `index.md` 直接阅读其分类框架章节与对比总表（一篇好综述梳理的几十上百篇文献脉络远胜盲抓散装摘要）。
2. **补齐最近 6–12 个月的新动向**
   - 综述发表存在时间滞后。额外用宿主 Web Search 检索最近一年（顶会 ICLR / NeurIPS / ICML / CVPR / ACL 及 arXiv / OpenReview）该方向热度最高的新分支或争议问题。
3. **保存检索记录与草稿**
   - 将检索词、参考的综述/聚合源及初步梳理写入 `workspaces/<project>/search_logs/stage1_landscape_raw.md` 返回给主 Agent。

### Step 2：向研究者做结构化汇报（先铺垫定义，再摆分类树）
主 Agent 读取 `stage1_landscape_raw.md` 后，按 [AGENTS.md](../../AGENTS.md) 沟通规范向用户呈现：

1. **核心概念与问题设定铺垫**：先用准确简练的学术语言把理解该方向必需的基础术语、输入输出形式与核心矛盾讲清楚（不用失真大白话比喻）。
2. **客观存在的学术分类树（Taxonomy）与时序轮廓**：
   - 该大方向天然分为哪几个主流技术流派（如持续学习中的正则约束、参数隔离/PEFT、记忆回放、梯度投影等）；
   - 每个流派各自的**代表性演进节点（从早期代表作到近期代表作）**；
   - 每个流派的**现实算力门槛**（如是否需要全参预训练、单卡能否跑通）与当前研究态势（哪些已经高度饱和、哪些仍有明显未解机制问题）。
3. **收敛提问**：结合用户的算力约束，指出哪 2–3 个细分枝杈最现实且有挖掘空间，请用户挑选或追问。

### Step 3：交互讨论与锁定 `01_scope.md`
- 用户追问某个分支细节时，必要时再做小范围定向补查。
- 当用户选定具体枝杈/演化线路（例如：“算力有限，我们就看基于正交/正则约束的 PEFT 持续学习这条线”）后：
  1. 确认该线路下的 **1–3 篇锚点种子论文（Seed Papers）** 及**明确排除的其他分支**；
  2. 参照 `templates/01_scope.md` 写入 `workspaces/<project>/01_scope.md`；
  3. 告知用户阶段 1 已完成落盘，建议开启新会话（或 `/compact`）进入 **阶段 2（`skills/idea-stage2-literature-map/SKILL.md`）**。
