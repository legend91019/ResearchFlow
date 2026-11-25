---
name: idea-stage3-ideation
description: Stage 3 of ResearchFlow Ideation. Guides evidence-tethered idea generation and refinement over 02_paper_map.md using JIT line-range source/code loading, dynamic reading depth upgrades, Explore/Challenge/Refine/Pivot state handling, and fact-vs-assumption tracking in 03_idea_discussion.md.
---

# Stage 3 — 锚点精读与受约束 Idea 推演 (`idea-stage3-ideation`)

本技能在 `01_scope.md` 与 `02_paper_map.md` 的基础上，通过人与主 Agent 的深度推演打磨出逻辑自洽、立足前人真实源码与实验证据的候选研究方案，并维护 `03_idea_discussion.md`。

---

## 一、启动准备（轻量上下文挂载）

会话开始时，主 Agent **仅读取**：
1. `workspaces/<project>/01_scope.md`
2. `workspaces/<project>/02_paper_map.md`
3. `workspaces/<project>/03_idea_discussion.md`（若已存在前序讨论）
4. 1–3 篇 `Direct Baseline` 的 `papers/<slug>/notes.md` 与 `papers/<slug>/index.md`

**不要预加载任何 `source/*.tex` 全文或 `repo/` 大代码文件**。

---

## 二、受约束构思引导透镜（Thinking Lenses — 引导推理，非机械表单）

从已有文献地图出发探讨新 Idea 时，严禁脱离锚点论文凭空拼凑模块。引导思考围绕以下三类自然科研切入视角展开：

1. **演化末端破局与混杂剥离（Lineage & Confound Lens — 默认主视角）**
   - 顺着 `A → B → C` 演进链，审视最新前沿 `C` 或 `Direct Baseline` 仍未解决的失效边界、或 `[作者声称]` 与 `[实验实证]` 之间的断层（例如：某方法的收益是否混杂了步长/容量/缓存预算不公平？某隐式假设在真实任务序列下是否崩溃？）。
   - 思考如何设计既能揭示真实机制边界、又能针对性消除该瓶颈的简洁方法。

2. **直接基线代码级手术（Anchor Surgery Lens）**
   - 对照 1–3 篇 `Direct Baseline` 的真实公式与代码实现，检查其目标函数、约束投影、记忆更新或路由模块是否存在冗余假设、优化冲突（如逐坐标预条件与子空间正交冲突）或过强限制，通过增、删（化繁为简）、改关键环节获得实质改进。

3. **跨子领域同构机制迁移（Cross-Domain Lens — 仅在需要或用户提出时启用）**
   - 当本路线内部手段受限时，将核心痛点抽象为通用数学/计算问题引入相邻子领域工具。
   - **强制自检**：必须回答“为什么不能直接生搬硬套？结合本任务特性必须解决什么特有的适配难点？”，拒绝无机制耦合的“A + B 硬缝合”。

---

## 三、JIT 原文/代码精准核验与阅读动态升档

在讨论过程中严格执行以下两条上下文与证据纪律：

1. **JIT 行区间精准加载（防脑补 & 防上下文累积）**
   - 一旦讨论聚焦到修改某篇论文的具体公式、核对某条定理成立条件、查看实验表细节或修改某个代码函数：
   - 先查 `papers/<slug>/index.md` 锁定对应文件与行号，再用文件读取工具**精确指定 `StartLine`–`EndLine`（每次 40–120 行）读取原始 `source/` 或 `repo/` 片段**（若公式含自定义宏，同步查看 `index.md` 标出的宏定义行）。
   - 若需要同时横向比对 3 个以上代码仓库的实现差异，派发一次性 `Reader Subagent` 完成比对并写入 `papers/code_comparison_<topic>.md`，主窗口仅读比对结果。

2. **阅读深度动态升档（Dynamic Upgrade）**
   - 如果原本仅做 `L0` 或 `L1` 阅读的某篇论文（例如某篇奠基理论工作或近期竞争论文）在讨论中突然成为关键论证支点或潜在撞车对象：
   - 立即调用 `fetch_paper.py`（如尚未拉取源码）并派发 `Paper Reader Subagent` 将其升档至 `L2`（精读公式与附录）或 `L3`（克隆并审计代码），更新其 `notes.md` 后再继续下结论。

---

## 四、讨论节奏与 `03_idea_discussion.md` 维护

1. **严格执行 `Explore` / `Challenge` / `Refine` / `Pivot` 准则**（见 [AGENTS.md](../../AGENTS.md) 第三节）：
   - 面对用户的发散探询（`Explore`），拿地图证据做客观利弊参照，不顺杆爬推翻主线；
   - 面对用户的根基质疑（`Challenge`），**绝不护短**，立刻回查原文与代码验证质疑是否成立；若原方案确有未排除的致命混杂或逻辑漏洞，主动将原前提移入风险项并建议调整或换方案。
2. **结构化区分“事实”与“假设”落盘**：
   - 当形成初步认可的候选 Idea、否决了某个重要分支、或者对话满 15–20 轮准备清窗续聊时，按 `templates/03_idea_discussion.md` 更新 `workspaces/<project>/03_idea_discussion.md`。
   - 务必确保 **`已验证事实`（有原文/代码坐标支撑）** 与 **`当前工作假设`（尚未被实验证实的推演前提）** 界限分明，并如实记录 **`已排除的方案及原因`**。
3. **进入阶段 4 的时机**：
   - 当用户对当前候选 Idea 的研究问题、核心机制改动与预期贡献表示认可，准备敲定并移交实验设计时，加载 **阶段 4（`skills/idea-stage4-review-handoff/SKILL.md`）** 启动独立反证审查。
