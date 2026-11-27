---
name: idea-stage2-literature-map
description: Stage 2 of ResearchFlow Ideation. Executes 4-angle deep search (3-tier citation graph, zero-lag arXiv stream, lateral routes, analogous/dual mechanisms, and counter-evidence), runs 2-hop local .bib co-citation radar, performs dynamic L0-L3 paper reading via isolated subagents, and builds a non-strawman 02_paper_map.md.
---

# Stage 2 — 四视角深搜与动态分级建图 (`idea-stage2-literature-map`)

本技能承接 `01_scope.md`，目标不是盲目堆砌论文数量，而是**摸清选定细分线路从 `A → B → C` 的完整机制演进、横向竞争路线、同构/对偶机制与负面反证证据**，产出一份事实与主张严格分离、绝不矮化前人工作的 `02_paper_map.md`。

---

## 一、Step 1：四视角深搜 + 零延迟预印本流（Deep Search Subagent）

读取 `workspaces/<project>/01_scope.md` 后，派发隔离的 `Deep Search Subagent` 围绕种子论文与细分问题，**必须覆盖以下四个检索视角与多源渠道**（若 `01_scope.md` 设有时间截断 `YYYY-MM-DD`，所有命令必须显式附加 `--before-date YYYY-MM-DD`，且严禁查阅或纳入截断日及之后的网页/文献/仓库）：

| 搜索视角 | 具体执行方式 | 核心目的 |
| :--- | :--- | :--- |
| **1. 纵向演化与零延迟流** | ① 对每篇种子论文运行 `python scripts/cite_graph.py <id> --direction both --limit 50 --out ... --json-out ...`（双源合并 + 最新前沿 `C` / 近 1–2 年顶会中坚 `B_recent` / 经典高引 `B_early` 三桶均衡）；<br>② 运行 `python scripts/cite_graph.py --arxiv-recent "<宽泛领域核心词>" --days 30 --limit 30` 直连 arXiv API 抓取最近 30 天零延迟新预印本（绕过搜索引擎对 48 小时内新文的索引滞后） | 理清 `A → B → C` 演进脉络，捕获刚挂出的贴身竞争工作 |
| **2. 横向路线与多渠道搜索** | 用宿主 Web Search 检索同一任务设定下采用其他技术路线的代表工作；**必须覆盖 `OpenReview`（含 Workshop 论文，防漏无 arXiv 版本的强相关工作）及 `ACL Anthology / CVF`**，检索词须并列同义动作词（如 `pruning OR simplification OR compression OR merging`），严禁用单一窄词锁死标题 | 看清本路线在全局坐标系中的真实优劣，消除渠道与同义词盲区 |
| **3. 相邻与对偶机制搜索** | 剥离当前业务名词，提炼底层数学/优化/统计机制关键词，**同时检索正向与逆向对偶算子**（例如做“多合一参数吸收”时，同步检索训练期的“一拆多保分布分裂重定位”；做“跨任务记忆治理”时，同步检索“单任务内上下文自适应删压”） | 识别已被相邻场景解决的数学对偶方程或潜在混杂机制 |
| **4. 反证与失效搜索（必做）** | 专门组合 `rethinking`、`revisiting`、`limitations`、`failure`、`instability`、`reproduction`、`illusion`、`when does ... help/fail` 等词检索 arXiv / OpenReview / Web | 在投入算力前，查明是否已有研究证明该路线存在伪增益、超参脆弱性或更平庸的替代解释 |

### 强制输出：防漏筛审计表（`search_logs/stage2_search_audit.md`）
子智能体完成初筛后挑选约 **15–25 篇**进入论文池，并按 `templates/search_audit.md` 写出审计文件（含 **`临界淘汰审计表 Borderline Excluded Top 5–10`**）。
> **防误杀硬规则**：
> 1. 凡与核心研究问题直接同赛道的**近 3–6 个月新预印本**，严禁以“刚发布、0 引用或无开源代码”为由仅看摘要就打入 `L0` 淘汰池；
> 2. 全栈系统/编解码器管线论文内部常藏有独立的评分或优化算子，初筛拿不准时必须拉取源码看方法章节公式再决定去留。

---

## 二、Step 2：候选分层与初始阅读等级分配（L0 → L3）

将入选论文按角色与初始阅读深度分级（身份不锁死，后续可随时动态升档）：

- **`Direct Baseline`（严控 1–3 篇，初始定为 `L3` 或 `L2`）**
  - **严苛准入标准**：① 方法本身逻辑与实验扎实、经得起推敲；② **有官方开源代码仓库**；③ 在该细分方向有较好认可度/代表性；④ 发表时间较新（优先近 1–2 年顶会或高关注新工作）。
  - 执行抓取（同时拉取原始源码与浅克隆官方代码仓）：
    ```bash
    python scripts/fetch_paper.py \
      --arxiv <id> \
      --workspace workspaces/<project> \
      --slug <year_shortname> \
      --repo <https://github.com/owner/repo> \
      --role "Direct Baseline"
    ```
- **`Counter-Evidence`（反证/复现/机制剖析论文）与高威胁 `Recent Frontier`（约 5–10 篇，强制至少 `L2`）**
  - **凡涉及核心理论边界、贴身竞争的近半年新工作或反证研究，必须调用 `fetch_paper.py` 拉取源码升至 `L2`（含检查 Appendix 中的定理推导与受控对比表）**，严禁停留在 `L1` 或 `L0`。
- **`Foundational / Survey`（约 3–5 篇，初始定为 `L1`）**
  - 用于锚定 `A → B → C` 的起点定义、标准问题形式化与经典对比基线（若为综述，必须通查 `index.md` 列出的全部附表）。
- **`Cross-Domain`（可选，默认 0 篇）**
  - 仅当明确需要借鉴相邻数学/系统机制或用户提出时纳入。

---

## 三、Step 3：隔离并行精读 + 本地 `.bib` 二跳共引补漏

1. **派发 `Paper Reader Subagent` 并行建档**（严禁主 Agent 在主窗口通读十几篇长文）：
   - 先读 `papers/<slug>/index.md` 定位宏定义（`macros.tex`）、章节、定理与实验表行号；
   - **L1（机制阅读）**：引言核心段、方法主干章节、主实验表（含 caption 与脚注）；
   - **L2（全文与附录精读）**：在 L1 基础上完整核对定理/命题条件、消融实验及 **Appendix 中的理论证明与特殊受控实验（如等范数/等预算表）**；
   - **L3（代码审计）**：在 L2 基础上对照 `repo/` 代码树，核查代码实际实现是否与论文公式完全一致（是否存在未写入正文的归一化、掩码缺失、样本删失或隐藏超参）；
   - 严格按 `templates/paper_note.md` 写入 `papers/<slug>/notes.md`，原样保留公式与源码坐标，强制拆分 `[作者声称]` 与 `[实验实证]`。

2. **强制执行本地 `.bib` 二跳共引雷达（零 API 开销防漏网）**：
   首批核心论文（尤其近半年最新预印本与综述）拉取解包后，**必须运行一次**：
   ```bash
   python scripts/cite_graph.py --scan-bib workspaces/<project> --year-min <近2-3年起算年份> --limit 25 --out workspaces/<project>/search_logs/stage2_bib_radar.md
   ```
   （配合 `--year-min` 可自动滤除早期通用数据集/指标论文，精准浮现近 2–3 年漏网竞争方法；历史回测模式附加 `--before-date YYYY-MM-DD`）。检查输出中被 `>= 2` 篇本地论文共同引用、但尚未归档的高相关文献；若发现漏掉的重要先驱或贴身对手，立即补拉建档并写入 `stage2_search_audit.md`。

---

## 四、Step 4：反稻草人汇总生成 `02_paper_map.md` 并与用户对齐

主 Agent 读取各篇 `papers/<slug>/notes.md` 与 `stage2_bib_radar.md`，参照 `templates/02_paper_map.md` 生成 `workspaces/<project>/02_paper_map.md`：
- **反稻草人核对纪律**：浓缩填写第 3 节对比矩阵时，必须如实保留前人工作已有的筛选、正则或兼容机制（例如前人已有参数空间 KL 筛选但缺图像曲率门控，必须如实写明，严禁笼统贬低为“无门控方法”）。
- 向用户清晰同步：① `A → B → C` 的完整演进故事；② 1–3 篇 `Direct Baseline` 的代码审计实况；③ 反证文献与二跳共引雷达揭示的警示或未解矛盾；④ 小方向主实验共识。

经用户确认后，建议开启新会话（或 `/compact`）进入 **阶段 3（`skills/idea-stage3-ideation/SKILL.md`）**。
