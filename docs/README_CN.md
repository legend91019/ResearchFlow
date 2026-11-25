<p align="center">
  <img src="assets/banner.svg" width="900" alt="ResearchFlow Banner">
</p>

<h3 align="center">
  <b>不重复造简陋的 Agent 运行时 —— 专注于设计编码智能体做科研的证据协议、信息组织与决策机制。</b>
</h3>

<p align="center">
  <a href="../LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="../pyproject.toml"><img src="https://img.shields.io/badge/Dependencies-零第三方强依赖-brightgreen" alt="Zero Core Dependencies"></a>
  <a href="../AGENTS.md"><img src="https://img.shields.io/badge/Host_Agents-Claude_Code_%7C_Codex_%7C_Antigravity-6366f1" alt="Compatible Host Agents"></a>
  <a href="../tests/"><img src="https://img.shields.io/badge/Tests-Passing-success?logo=pytest&logoColor=white" alt="Tests Passing"></a>
</p>

<p align="center">
  <a href="../README.md">🇺🇸 English</a> · <b>🇨🇳 简体中文</b>
</p>

<p align="center">
  <a href="#-为什么做-researchflow">为什么做 ResearchFlow？</a> ·
  <a href="#️-核心架构科研工作空间协议">核心架构</a> ·
  <a href="#-idea-研究四阶段工作流">四阶段工作流</a> ·
  <a href="#-快速开始">快速开始</a> ·
  <a href="#️-与现有开源系统的对比">系统对比</a> ·
  <a href="#️-确定性命令行工具">命令行工具</a> ·
  <a href="#️-演进路线图">路线图</a>
</p>

---

## 🔥 最新动态

- **[2026-11] `v0.1.0` 正式发布** — 推出 **ResearchFlow** 第一阶段（**实证型 Idea 讨论与文献建图协议**）：
  - 全局科研认识论宪法（[`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md)），强制执行“证据四分法”与 `Explore / Challenge / Refine / Pivot` 四态讨论控制；
  - 4 个按阶段按需加载的模块化科研技能（[`skills/`](../skills/)），彻底避免多阶段提示词撑爆上下文；
  - 2 个零第三方强依赖的确定性 Python 工具：[`cite_graph.py`](../scripts/cite_graph.py)（Semantic Scholar + OpenAlex 双源容错双向引文网络）与 [`fetch_paper.py`](../scripts/fetch_paper.py)（arXiv 原始 LaTeX 无损解包、多文件 `\input` 拓扑与行号索引生成、官方代码仓浅克隆）。

---

## 🤔 为什么做 ResearchFlow？

市面上不少开源 Auto-Research 系统主打*“输入一句话，全自动产出一篇顶会论文”*。但在真实前沿 AI 课题上深度体验后就会发现，**Idea 构思恰恰是现有自动化工具与人类研究者差距最大、最容易产出废品的环节**：

1. **逐层摘要导致的信息漂移（`摘要 → 知识卡片 → 综述 → 假设`）**
   把截断到 800 字的摘要压成卡片、再把前 24 张卡片压成一篇综述，原论文的精确数学定义、隐式成立条件、未对齐的超参混杂变量和表格脚注早已丢失殆尽。模型最终只是在二手口号上排列组合。
2. **先射箭后画靶（未读文献先盲猜创新点）**
   不少流水线在第 1 步还没检索任何真实论文时，就让大模型凭先验概率编造 `Novel Angle`、钦定 `Benchmark` 甚至预估涨点幅度，导致整条下游链路建立在幻觉前提之上。
3. **单一引文圈回音室与反证缺失**
   单纯依赖关键词 API 并按引用数排序截断，不仅会把近 6–12 个月刚挂出来 0 引用的直接撞车论文挤出视野，还会漏掉负面复现研究与相邻子领域的同构数学机制分析。
4. **上下文涣散与讨好型跑偏（Sycophancy Drift）**
   在同一聊天窗口里连刷几十次搜索和长文阅读会严重稀释模型注意力；同时大模型极易“顺杆爬”——人类随口追问一句旁支想法，模型立刻推翻原本扎实的主线去迎合新词。
5. **7 万行重复造轮子的脆弱工程壳子**
   用几万行自定义 Python 循环、正则解析和简陋 CLI 去重造 Agent 运行时，既挤占上下文又充满静默降级 Bug——而现代原生编码宿主（**Claude Code**、**Codex**、**Antigravity**）本身就已经具备极强的搜索、文件操作与子智能体隔离能力。

### 我们的核心主张

> **ResearchFlow 不是另一套大包大揽的多智能体后台框架，而是一套 *科研工作空间协议（Research Workspace Protocol）*。**
> **宿主 Agent** 负责执行、联网与子智能体隔离；**Skill 规范** 负责科研认识论与上下文卫生；**项目磁盘文件** 负责唯一可审计的长期知识状态；**人类研究者** 掌握每一次关键科学判断。

---

## 🏛️ 核心架构：科研工作空间协议

```mermaid
flowchart TB
    Human["👤 人类研究者<br/>方向收敛 · 质疑前提 (Challenge) · 关键科研拍板"]
    Host["🧠 宿主主 Agent (Claude Code / Codex / Antigravity)<br/>自然科研对话 · 按行号 JIT 原片核验 · 状态流转"]

    subgraph Protocol["📜 全局协议与按需阶段技能"]
        Constitution["AGENTS.md / CLAUDE.md<br/>证据四分法 · Explore/Challenge/Refine/Pivot"]
        S1["idea-stage1-landscape"]
        S2["idea-stage2-literature-map"]
        S3["idea-stage3-ideation"]
        S4["idea-stage4-review-handoff"]
    end

    subgraph Subagents["🛡️ 上下文隔离任务角色 (一次性独立窗口)"]
        SubSurvey["Survey Subagent<br/>综述优先与分类树梳理"]
        SubDeep["Deep Search Subagent<br/>四视角检索 + 临界淘汰审计"]
        SubReader["Paper Reader Subagents<br/>L1–L3 原文与代码审计"]
        SubCritic["Critical Reviewer Subagent<br/>零历史包袱独立反证审查"]
    end

    subgraph Tools["⚙️ 确定性辅助脚本 (scripts/)"]
        CiteGraph["cite_graph.py<br/>S2 + OpenAlex 双向引文网络"]
        FetchPaper["fetch_paper.py<br/>arXiv 原始源码解包 + 行号索引 + 代码浅克隆"]
    end

    subgraph Disk["💾 项目磁盘：唯一持久化知识状态 (workspaces/&lt;project&gt;/)"]
        F1["01_scope.md"]
        F2["02_paper_map.md"]
        F3["03_idea_discussion.md"]
        F4["04_handoff.md"]
        Papers["papers/&lt;slug&gt;/<br/>source/ · index.md · notes.md · repo/"]
        Logs["search_logs/<br/>临界淘汰审计表 · 独立反证报告"]
    end

    Human <--> Host
    Protocol --> Host
    Host --> Subagents
    Subagents --> Tools
    Host --> Tools
    Subagents --> Disk
    Host <--> Disk
```

### 四大核心机制设计

| 核心支柱 | ResearchFlow 具体机制 | 解决的真实痛点 |
| :--- | :--- | :--- |
| **1. 证据四分法** | 一切论文档案与讨论文档强制拆开标注：`[作者声称]`、`[实验实证]`（含未控制的混杂变量）、`[模型推断]`、`[未验证假设]`。 | 彻底杜绝把前人论文 Introduction 里的包装口号当成已证实的科学事实。 |
| **2. 原始材料零删改 + JIT 行号挂载** | `fetch_paper.py` 将 `papers/<slug>/source/`（含 `macros.tex`、`appendix.tex`）原封不动保留并生成行号索引 `index.md`；主窗口推演时每次只按行号挂载 **40–120 行**原片。 | 公式与表格细节零压缩失真，同时保证主对话窗口上下文极度干净。 |
| **3. 子智能体隔离 + 临界淘汰审计** | 脏搜索与批量长文阅读全部交由一次性 Subagent 执行；搜索子智能体必须在 `search_logs/` 输出 **临界淘汰名单（Borderline Excluded Top 5–10）**。 | 隔离几万字检索噪音，同时让研究者花 10 秒扫视即可防止子智能体误杀关键论文。 |
| **4. 四态讨论控制 + 独立盲审反证** | 严格区分 `Explore`（随口探询）与 `Challenge`（质疑根基假设），并在定稿移交前拉起**零历史包袱的 `Critical Reviewer`** 做五问反证。 | 既防讨好式跑偏，又防止主 Agent 顺着既有偏好替错误假设护短（确认偏误）。 |

---

## 🔬 Idea 研究四阶段工作流

ResearchFlow 将科研前期的构思过程划分为四个递进阶段，每个阶段仅按需加载对应的单个 [`SKILL.md`](../skills/)，并通过磁盘状态文件无缝接力：

### 阶段 1 — 综述优先广搜与细分分支锁定（[`idea-stage1-landscape`](../skills/idea-stage1-landscape/SKILL.md)）
- **支持双起点入口**：
  - *宽泛方向模式*：派发 `Survey Subagent` 优先检索近 2–3 年高质量综述（直接拉取 `.tex` 阅读其分类框架）、Tutorial 与 GitHub `Awesome-*` 仓库，并用网页搜索补齐近 6–12 个月新动向。
  - *种子论文直入模式*：若手里已有 1–3 篇目标论文，直接核对范围写入 `01_scope.md`，跳过泛搜直入阶段 2。
- **先铺垫精确定义，再摆学术分类树（Taxonomy）**：拒绝生硬失真的大白话比喻，先用简练准确的学术语言交代核心概念与问题设定，再梳理客观存在的技术流派、`A → B → C` 演进雏形与算力门槛。
- **阶段产物**：`01_scope.md`（锁定**问题空间与演化分支**，绝不在此刻预设具体新算法）。

### 阶段 2 — 四视角深搜与动态 `L0–L3` 论文地图（[`idea-stage2-literature-map`](../skills/idea-stage2-literature-map/SKILL.md)）
为避免陷入单一引文小圈子，`Deep Search Subagent` 必须覆盖**四个正交搜索视角**：
1. **纵向演化搜索（`cite_graph.py` + Web）**：拉取种子论文的双向引文网，前向施引采用**高引里程碑 `B` + 零引用最新工作 `C` 双桶均衡筛选**，完整还原 `A → B → C` 时间线并防撞车。
2. **横向路线搜索**：检索同一任务设定下采用其他技术流派的代表性工作。
3. **相邻机制搜索**：剥离业务包装词，检索相邻子领域中的同构数学/优化机制。
4. **反证与失效搜索（必做）**：专门检索负面结论、复现质疑、超参敏感性与失效边界分析（`rethinking`、`revisiting`、`limitations`、`instability`）。

对入选的 15–25 篇文献执行可动态升档的分级阅读（`Paper Reader Subagent`）：
- **`L0` 相关性筛查** → **`L1` 核心机制与主表** → **`L2` 全文推导与附录深读** → **`L3` 官方代码仓实现审计**（锁定 commit，核查代码实际实现是否与论文公式一致、有无隐藏工程 trick）。
- **直接基线（`Direct Baseline`，严控 1–3 篇）** 必须满足四条硬标准：方法经得起推敲、有官方开源代码、在领域内有认可度、发表时间较新。
- **阶段产物**：`02_paper_map.md` + 单篇档案 `papers/<slug>/notes.md` + 防漏筛记录 `search_logs/stage2_search_audit.md`。

### 阶段 3 — 原文切片 JIT 挂载与受约束构思（[`idea-stage3-ideation`](../skills/idea-stage3-ideation/SKILL.md)）
- 通过三类科研思考透镜引导推理（非僵化程序表单）：**演化末端破局与混杂剥离**、**直接基线代码级手术**、以及**按需开启的跨子领域机制迁移**。
- 凡讨论具体公式修改、定理前提或代码手术，必须查 `papers/<slug>/index.md` 按起止行号精准加载 `source/` 或 `repo/` 中对应的 **40–120 行原片**；若某篇 `L1` 论文突然成为论证关键，当场动态升档至 `L2/L3`。
- 严格执行 **`Explore` / `Challenge` / `Refine` / `Pivot`** 规则：面对用户对基本假设的质疑（`Challenge`，如“涨点是不是仅因梯度变小了？”），严禁护短，立即回查原论文实验控制组是否排除了该混杂变量。
- **阶段产物**：`03_idea_discussion.md`（严格分栏保存*已验证事实*、*当前工作假设*、*候选方案*与*已排除废案原因*）。

### 阶段 4 — 历史隔离反证审查与主实验共识交接（[`idea-stage4-review-handoff`](../skills/idea-stage4-review-handoff/SKILL.md)）
- **零历史包袱独立挑刺**：不做“7.5/10”式的算命打分，而是启动一个**完全没看过此前聊天妥协过程**的 `Critical Reviewer Subagent`，仅喂入客观方案与原始论文证据，独立联网查重并逐一回答五问：
  1. *换同义术语检索近半年 arXiv / OpenReview，是否已有实质相同的工作发表？*
  2. *候选方案声称要解决的前人缺陷，在 `Direct Baseline` 原文与原代码里真的存在吗？*
  3. *如果指标上涨，是否存在更简单平庸的替代解释（如隐式降学习率、额外参数/存储开销）？*
  4. *在算力边界内，拟议实验能否真正证伪核心假设？*
  5. *从数学或优化机制看，真实训练最可能翻车在哪一步？*
- **主实验共识接力包导出**：审查通过并由人类拍板后，依据 `02_paper_map.md` 中近期论文的实际主表，导出 `04_handoff.md`——包含精确到文件行号的公式/代码改动坐标、领域公认的主实验 Benchmark 与主指标、以及对齐近期论文对比规模的必比 Baseline 名单（经典奠基 + 1–3 篇直接基线 + 近 1 年最新前沿）。

---

## ⚖️ 与现有开源系统的对比

| 对比维度 | AutoResearchClaw | autoresearch (Karpathy) | Agentic Scientist (AI-Scientist-v3) | AgentLaboratory | AI-Researcher | **ResearchFlow** |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **运行载体架构** | 自建 23 阶段重型 Python 管线（~7.1 万行） | 宿主编码 Agent + `program.md` | Docker 内置 Headless 编码 Agent + `SKILL.md` | 自建 Python 多角色对话循环 | 自建 Docker 多智能体框架 | **原生编码宿主 + 科研工作空间协议（~2,200 行）** |
| **任务输入起点** | 宽泛主题词（第 1 步先盲写未核实的 `goal.md`） | 人类预置 `prepare.py` + `train.py` + 单一指标 | 预置 `task.md` + 只读评分器 `evaluate.py` | 主题描述 + 人工备注 | 预给 `source_papers` + 任务书 | **宽泛大方向 或 1–3 篇种子论文（严禁前置脑补）** |
| **文献检索策略** | 关键词 API 抓取 + 字符硬截断初筛 | 无文献检索（纯实验迭代） | 写论文阶段后置检索 | ArXiv 摘要循环（默认收满 5 篇即停） | 依赖给定种子文献 + 代码搜索 | **综述优先广搜 + 四视角深搜（含反证检索与双源均衡引文网）** |
| **文献阅读保真度** | 800 字截断摘要 → 前 24 张卡片拼综述 | 不适用 | 读任务文件与本地实验记忆 | 5 万字 PDF 文本（3 步自动过期清退） | 翻页浏览 `.tex` + `Code Survey` | **`source/` 原始 `.tex` 零修改保留 + 行号索引 `index.md` + JIT 原片挂载 + `L0–L3` 代码审计** |
| **认知防漂移机制** | 单篇 Markdown 综述生成 | `val_bpb` 指标优胜劣汰 | 指标门槛 + `source_contains` 静态校验 | 博后与博士生自由对话 | 发散生成 5 个方案再自选 | **证据四分法（声称/实证/推断/假设）+ `Challenge` 假设质询** |
| **防确认偏误机制** | 非阻断词面 Jaccard 新颖性分数 | 真实训练指标硬验证 | 密封终测集评测 | 可选人工打回重试 | 模型自我择优提示词 | **历史隔离的 `Critical Reviewer` 子智能体（跨术语查重 + 混杂归因拷问）** |

---

## ⚡ 快速开始

### 1. 克隆仓库与可选依赖

仓库内的辅助脚本**核心功能 100% 基于 Python 3.10+ 标准库**，无需安装任何第三方包即可运行。仅当你需要解析没有 LaTeX 源码的纯 PDF 论文时，可选安装 `pymupdf`：

```bash
git clone https://github.com/legend91019/ResearchFlow.git
cd ResearchFlow

# 可选：安装纯 PDF 回退解析支持与 pytest 测试工具
pip install -e ".[pdf,dev]"
```

*(可选)* 配置学术 API 环境变量以获得更高速率配额：
```bash
export S2_API_KEY="你的_Semantic_Scholar_Key"   # 可选：无 Key 遇 HTTP 429 限流时会自动无缝切换 OpenAlex
export OPENALEX_EMAIL="you@university.edu"      # 可选：加入 OpenAlex 礼貌池提升免费并发额度
```

### 2. 在宿主编码 Agent 中打开并直接对话

使用 **Claude Code**、**Codex** 或 **Antigravity** 打开 `ResearchFlow/` 根目录，宿主会自动读取 [`AGENTS.md`](../AGENTS.md) / [`CLAUDE.md`](../CLAUDE.md) 并按阶段加载对应技能。

#### 方式 A：从宽泛大方向开始（完整走阶段 1 → 4）
```text
我想研究大模型持续学习（Continual Learning）方向，手头算力是单张 24GB 显卡。
请创建工作空间 workspaces/cl_peft，开始阶段 1 方向广搜与分类树梳理。
```

#### 方式 B：手里已有 1–3 篇种子论文（跳过广搜，直入阶段 2）
```text
我想围绕 O-LoRA (arXiv:2310.06762) 和 InfLoRA (arXiv:2404.00228) 所在的持续 PEFT 正交子空间路线找改进点，
算力上限单张 RTX 4090。请初始化 workspaces/ortho_cl，直接进入阶段 2 四视角深搜与论文建图。
```

#### 跨阶段清理上下文与断点续聊
由于每个阶段的事实、工作假设与废案归档都结构化保存在 `workspaces/<project>/` 下，每走完一个阶段（或对话超过 15–20 轮时），你可以随时执行 `/compact` 或直接新开一个干净会话无缝续接：
```text
请读取 workspaces/ortho_cl/01_scope.md 和 workspaces/ortho_cl/02_paper_map.md，
我们继续进行阶段 3 的 Idea 推演。
```

<details>
<summary>📂 <b>点击查看课题工作区产物目录与自动生成的 <code>index.md</code> 示例</b></summary>

```text
workspaces/ortho_cl/
├── 01_scope.md                         # 学术分类树、算力边界、锁定的 A→B→C 细分分支与种子论文
├── 02_paper_map.md                     # 时序演进脉络、机制/混杂控制对比矩阵、主实验共识统计
├── 03_idea_discussion.md               # 已验证事实 vs. 工作假设、候选方案规格、已排除废案及原因
├── 04_handoff.md                       # 定稿公式/代码改动坐标与对齐近期文献的主实验接力包
├── search_logs/
│   ├── stage2_search_audit.md          # 四视角检索轨迹 + 临界淘汰名单 (Borderline Excluded Top 5-10)
│   └── critical_review.md              # 历史隔离的五问反证与跨术语撞车审查报告
└── papers/
    └── 2023_olora/
        ├── source/                     # 一字未改的原始 arXiv .tex 源码、macros.tex、tables/、.bib
        ├── repo/                       # 浅克隆的官方 GitHub 代码库（锁定 commit SHA）
        ├── metadata.json               # 标题、作者、年份、原始包 SHA-256 校验值、仓库 commit
        ├── index.md                    # 精确到 file:Lstart-Lend 的宏定义、章节、实验表、公式索引
        └── notes.md                    # 证据四分法阅读档案（支持 L1 → L2 → L3 动态升档）
```

自动生成的 `papers/<slug>/index.md` 片段示例：
```markdown
## 1. Custom Macros & Notation Definitions (Read Before Interpreting Equations)
- `source/macros.tex:L2-L38` (19 definitions, e.g. `\proj`, `\subspace`, `\orthloss`)

## 2. Section & Appendix Line Index (Use Line Ranges for JIT Reading)
- **Introduction** — `source/sections/intro.tex:L1-L74`
- **Proposed Method** — `source/sections/method.tex:L1-L18`
  - **Orthogonal Subspace Constraint** — `source/sections/method.tex:L19-L96`
- **Appendix** — `source/appendix.tex:L1-L142`

## 3. Experimental & Summary Tables
- `source/tables/main_results.tex:L1-L34` (`tab:main`): Main comparison across 15 continual learning benchmarks.
```

</details>

---

## 🛠️ 确定性命令行工具

[`scripts/`](../scripts/) 下的两个脚本也可在终端中独立调用：

### 1. `scripts/cite_graph.py` —— 双源容错双向引文网络
联合查询 **Semantic Scholar** 与 **OpenAlex** 并跨源去重（DOI → arXiv ID → 归一化标题）。当未配置 Key 导致 Semantic Scholar 返回 `HTTP 429` 时，自动无缝切换至 OpenAlex 并显式记录诊断信息；施引文献采用**高引关键节点 `B` + 最新零引用前沿 `C` 均衡分桶**，兼顾脉络完整性与最新防撞车需求。

```bash
python scripts/cite_graph.py 2310.06762 \
  --direction both \
  --limit 40 \
  --year-min 2022 \
  --with-abstracts \
  --out workspaces/demo/search_logs/olora_graph.md \
  --json-out workspaces/demo/search_logs/olora_graph.json
```

### 2. `scripts/fetch_paper.py` —— 原始源码无损解包与行号索引器
下载 arXiv e-print `.tar.gz` / `.gz` 源码包（内置路径穿越与 SSRF 防护），**保证 `source/` 下所有原始文件零删改**；自动解析 `\input` / `\include` 多文件引用拓扑，提取自定义宏文件、章节层级、实验表格、定理与带标签公式的精确 `file:Lstart-Lend` 行号区间，并支持浅克隆官方开源代码库。

```bash
python scripts/fetch_paper.py \
  --arxiv 2310.06762 \
  --workspace workspaces/demo \
  --slug 2023_olora \
  --repo https://github.com/cmnfriend/O-LoRA \
  --with-pdf \
  --role "Direct Baseline"
```

---

## 📂 仓库目录结构

```text
ResearchFlow/
├── AGENTS.md                        # 全局科研工作空间协议（Codex / Antigravity / OpenCode 自动加载）
├── CLAUDE.md                        # Claude Code 入口指引（指向 AGENTS.md）
├── docs/
│   ├── README_CN.md                 # 简体中文说明文档
│   └── assets/banner.svg            # 矢量架构横幅图
├── skills/                          # 按阶段按需读取的模块化科研技能
│   ├── idea-stage1-landscape/       # 阶段 1：综述优先广搜与学术分类树定界
│   ├── idea-stage2-literature-map/  # 阶段 2：四视角深搜、防漏筛审计与 L0–L3 动态建图
│   ├── idea-stage3-ideation/        # 阶段 3：JIT 原文/源码切片核验与受约束推演
│   └── idea-stage4-review-handoff/  # 阶段 4：历史隔离反证审查与主实验共识交接
├── scripts/                         # 零第三方强依赖的确定性辅助 CLI
│   ├── cite_graph.py                # S2 + OpenAlex 双向引文网络工具
│   └── fetch_paper.py               # arXiv/PDF 原始材料抓取、LaTeX 行号索引与仓库浅克隆
├── templates/                       # 01–04 阶段文档、单篇阅读档案与检索审计表模板
├── tests/                           # 脚本功能与协议完整性单元测试
└── workspaces/                      # 本地课题工作空间目录（默认 git 忽略）
```

---

## 🗺️ 演进路线图

ResearchFlow 按完整 AI 科研生命周期分四个大阶段逐步构建：

- [x] **第一阶段 — 实证型 Idea 讨论与文献建图（`v0.1`，已完成）**
  - 综述优先分类树定界、含反证视角的四向深搜、原始 LaTeX 行号索引、`Explore / Challenge / Refine / Pivot` 讨论控制与独立 `Critical Reviewer` 反证交接。
- [ ] **第二阶段 — 文献共识驱动的实验与消融设计（`v0.2`，规划中）**
  - 承接 `04_handoff.md` 与 `02_paper_map.md`，构建严控混杂变量的实验矩阵、消融实验、诊断探针与运行前公平性核查。
- [ ] **第三阶段 — 预算感知的可靠实验执行与故障诊断（`v0.3`，规划中）**
  - 确定性评测沙箱、算力时间预算护栏、断点续跑队列与代码实现忠实度审计。
- [ ] **第四阶段 — 实验结果分析、科研绘图与证据绑定论文撰写（`v0.4`，规划中）**
  - 反事实机制剖析、出版级图表生成、以及严格绑定真实实验 JSON 与一手文献引用的论文生成与审稿迭代。

---

## 🧪 运行测试

```bash
pytest -v
```

---

## 📜 致谢与参考系统

ResearchFlow 的设计源于对现有开源自动科研系统的深度源码剖析与实战反思，重点参考并对比了 [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw)、[autoresearch](https://github.com/karpathy/autoresearch)、[The Agentic Scientist (AI-Scientist-v3)](https://github.com/SakanaAI/AI-Scientist-v3)、[AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) 与 [AI-Researcher](https://github.com/HKUDS/AI-Researcher)。

## 📄 开源协议

本项目基于 [MIT License](../LICENSE) 开源。
