---
name: idea-stage2-literature-map
description: Stage 2 of ResearchFlow Ideation. Executes 4-angle deep search (longitudinal citation graph, lateral routes, analogous mechanisms, and counter-evidence), logs borderline exclusions, performs dynamic L0-L3 paper reading via isolated subagents, and builds 02_paper_map.md.
---

# Stage 2 — 四视角深搜与动态分级建图 (`idea-stage2-literature-map`)

本技能承接 `01_scope.md`，目标不是盲目堆砌论文数量，而是**摸清选定细分线路从 `A → B → C` 的完整机制演进、横向竞争路线与负面反证证据**，产出一份事实与主张严格分离的 `02_paper_map.md`。

---

## 一、Step 1：四视角深搜与防漏筛审计（Deep Search Subagent）

读取 `workspaces/<project>/01_scope.md` 后，派发隔离的 `Deep Search Subagent` 围绕种子论文与细分问题，**必须覆盖以下四个检索视角**（严禁只沿着单一引文圈自嗨）：

| 搜索视角 | 具体执行方式 | 核心目的 |
| :--- | :--- | :--- |
| **1. 纵向演化搜索** | 对 `01_scope.md` 中的每篇种子论文运行 `python scripts/cite_graph.py <id> --direction both --limit 50 --out ... --json-out ...`，并结合近期 Web Search 补齐 API 尚未收录的新预印本 | 理清该线路如何从早期 `A` → 中期 `B` → 近 1 年最新工作 `C` 逐步演进，防撞车 |
| **2. 横向路线搜索** | 用宿主 Web Search 检索**同一任务设定下采用其他技术路线**的近期代表性高水平工作（2–4 篇） | 看清本路线在全局坐标系中的真实优劣，避免局部视野盲区 |
| **3. 相邻机制搜索** | 剥离当前业务名词，提炼底层数学/优化/系统机制关键词（如子空间投影、谱门控、校准漂移等），检索相邻子领域的同构分析工作 | 识别潜在混杂机制（如步长缩放效应）或可借鉴工具 |
| **4. 反证与失效搜索（必做）** | 专门组合 `rethinking`、`revisiting`、`limitations`、`failure`、`instability`、`reproduction`、`when does ... fail` 等词检索 arXiv / OpenReview / Web | 在投入算力前，查明是否已有研究证明该路线存在伪增益、超参脆弱性或更平庸的替代解释 |

### 强制输出：防漏筛审计表（`search_logs/stage2_search_audit.md`）
子智能体完成初筛（`L0` 级别：标题 + 摘要 + 发表场所）后，挑选约 **15–25 篇**进入论文池，并必须按 `templates/search_audit.md` 写出审计文件，其中**必须包含 `临界淘汰审计表（Borderline Excluded Top 5–10）`**。
主 Agent 读取该表后，向用户简要同步检索概况与临界淘汰名单，确认无重要文献被误杀。

---

## 二、Step 2：候选分层与初始阅读等级分配（L0 → L3）

将入选的 15–25 篇论文按角色与初始阅读深度分级（身份不锁死，后续讨论可随时动态升档）：

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
- **`Counter-Evidence`（反证/复现/机制剖析论文）与关键 `Recent Frontier`（约 5–10 篇，初始定为 `L2` 或 `L1`）**
  - 凡涉及核心争议、负面结论或贴身竞争的近 1 年新工作，调用 `fetch_paper.py` 拉取原始源码包。
- **`Foundational / Survey`（约 3–5 篇，初始定为 `L1`）**
  - 用于锚定 `A → B → C` 的起点定义、标准问题形式化与经典对比基线。
- **`Cross-Domain`（可选，默认 0 篇）**
  - 仅当用户明确希望从其他子领域寻找迁移灵感时纳入。

---

## 三、Step 3：隔离并行精读与证据四分法建档（Paper Reader Subagent）

**严禁主 Agent 在主对话里连续通读十几篇论文全文**。按单篇（或同组 2–3 篇 L1 论文）派发独立的 `Paper Reader Subagent`：

1. **阅读规范（基于原始 `source/` 与 `index.md`）**：
   - 先读 `papers/<slug>/index.md` 查看宏定义文件（如 `macros.tex`）、章节起止行号与表格位置；
   - **L1（机制阅读）**：读取引言核心段、方法主干章节、主实验表（含 caption 与脚注）；
   - **L2（全文精读）**：在 L1 基础上完整核对定理/推导、消融实验与 Appendix 中的超参/特殊设置；
   - **L3（代码审计）**：在 L2 基础上对照 `repo/` 代码树，定位核心算法与训练循环所在文件及函数行号，**核查代码实际实现是否与论文公式完全一致（是否存在未写入正文的归一化、裁剪、特殊学习率等工程 trick）**。
2. **输出规范（写入 `papers/<slug>/notes.md`）**：
   - 严格遵循 `templates/paper_note.md`；
   - **核心公式原样保留**并附 `source/<file>:L<start>-L<end>` 坐标；
   - **强制拆分 `[作者声称]` 与 `[实验实证]`**，明确指出实验未单独控制的混杂变量与未验证缺口。

---

## 四、Step 4：汇总生成 `02_paper_map.md` 并与用户对齐

主 Agent 读取各篇 `papers/<slug>/notes.md`（不读原始长文），参照 `templates/02_paper_map.md` 生成 `workspaces/<project>/02_paper_map.md`，向用户清晰汇报：
1. **该细分方向从 `A → B → C` 的完整演进故事**（每一步到底改了什么、为什么改、最新停在哪里）；
2. **1–3 篇候选 `Direct Baseline` 的资质核验与代码审计发现**；
3. **反证搜索发现了什么警示或未解矛盾**；
4. **近期论文的主实验共识（大家公认在测什么 Benchmark、对比哪些 Baseline）**。

经用户确认地图无重大遗漏后，提示可开启新会话（或 `/compact`）进入 **阶段 3（`skills/idea-stage3-ideation/SKILL.md`）**。
