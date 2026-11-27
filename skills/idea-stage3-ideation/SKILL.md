---
name: idea-stage3-ideation
description: Stage 3 of ResearchFlow Ideation. Guides parsimonious, evidence-tethered idea generation over 02_paper_map.md with strict complexity budgets (anti-accretion), mandatory component search-back, JIT line-range source/code loading, and Explore/Challenge/Refine/Pivot state tracking in 03_idea_discussion.md.
---

# Stage 3 — 锚点精读与受约束极简构思 (`idea-stage3-ideation`)

本技能在 `01_scope.md` 与 `02_paper_map.md` 的基础上，通过人与主 Agent 的深度推演打磨出**科学问题聚焦、机制简洁有力、立足前人真实源码与实验证据**的候选研究方案，并维护 `03_idea_discussion.md`。

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

从已有文献地图出发探讨新 Idea 时，严禁脱离锚点论文凭空拼凑模块。围绕以下三类自然科研切入视角展开：

1. **文献冲突与混杂破局透镜（Conflict & Confound Lens — 最高价值主视角）**
   - 审视 `02_paper_map.md` 中最新前沿 `C` 暴露出的**表面相反结论或未解机制张力**（例如：为什么一派论文主张谱均衡抗遗忘，另一派主张低秩集中抗遗忘？为什么某种代理指标在部分场景有效而在另一场景崩溃？），或 `[作者声称]` 与 `[实验实证]` 之间的混杂断层。
   - 优先寻找能够**统一解释该矛盾并导出精准判别/控制准则**的核心科学切入点，而非单纯堆砌工程技巧刷榜。

2. **直接基线代码级手术透镜（Anchor Surgery Lens）**
   - 对照 1–3 篇 `Direct Baseline` 的真实公式与代码实现，检查其目标函数、几何约束或状态更新是否存在过强近似、方向信息浪费（如把矩阵各向异性曲率压成标量迹）或优化冲突，通过**化繁为简或精准重构关键一项**获得本质改进。

3. **跨子领域同构机制迁移透镜（Cross-Domain Lens — 仅在需要或用户提出时启用）**
   - 将核心痛点抽象为通用数学/统计问题引入相邻领域工具。
   - **强制自检**：① 必须回答结合本任务结构必须解决什么特有的适配难点（拒绝 `A + B` 生硬缝合）；② **必须立即做“奥卡姆初等占优自检”**——确认该高阶数学工具在当前设定下没有退化为 1–2 行初等闭式公式（如零失败停时下的赌博超鞅退化为初等超几何分布）。

---

## 三、反拼盘复杂度预算与新增算子回搜铁律（Anti-Accretion & Search-Back）

这是防止自动化推演滑向“多模块工程缝合怪”的核心红线，必须在整个 Stage 3（及 Stage 4 退回修改时）严格执行：

1. **剥离“基线工程纠偏”与“本文核心科学贡献”（Clean Baseline Separation）**
   - Stage 2 代码审计挖出的前人实现 Bug、数据泄漏、缺失掩码或已知执行层前缀技巧（如 `InfLoRA-Clean`、`Ans-Prefix`），**必须单独归入公平对齐强基线**，严禁将其包装为本文的方法创新支柱。

2. **核心机制极简预算（Complexity Cap：1–2 个紧耦合原语）**
   - **严禁“一个前人痛点配一个补丁模块”**（严禁发现 4 个问题就拼出 `Module 1 + Module 2 + Module 3 + Module 4` 外加五六个手工权重）。
   - 候选方案的核心方法创新**原则上锁定 1 个核心原语（至多不超过 2 个数学上不可拆分的紧耦合机制）**；若需要借用现成的统计校准壳（如 `LTT`）或基础预处理，必须明确标为“标准基础设施引用”，不占创新声明。
   - **反棘轮膨胀准则**：当方案在推演或审稿返修中遇到边缘反例时，**优先通过升级原目标函数统一消解**（例如用单步训练折对数似然比替代 6 个手工启发式权重）或**诚实收敛研究问题边界**，严禁每遇到一个反例就外挂一层新补丁。

3. **新增子机制强制回跳查重（Mandatory Component Search-Back）**
   - 一旦 Stage 3 讨论（或 Stage 4 返修）新引入了某个在 Stage 2 未曾专门检索过的子技术、数学正则项或物理守恒算子：
   - **必须当场暂停定稿**，剥离原业务包装词，用该子机制的通用学术术语（含正逆对偶概念，如 `split/relocation <-> merge/absorption`、`context adaptation <-> memory pruning`）执行一轮宿主搜索 + `python scripts/cite_graph.py --scan-bib workspaces/<project> --keyword "<regex>"`（回测模式加 `--before-date`），若发现高相关前人工作立即调用 `fetch_paper.py` 升档核对，绝不允许盲目并入。

---

## 四、JIT 原文/代码精准核验与阅读动态升档

1. **JIT 行区间精准加载（防脑补 & 防上下文累积）**
   - 凡触及具体公式修改、定理成立条件、实验表特殊设置或代码函数改造，先查 `papers/<slug>/index.md` 定位文件与行号，再用文件读取工具精确加载 **40–120 行**原始 `source/` 或 `repo/` 片段（含 `macros.tex` 符号定义）。
   - 如需同时横向比对 3 个以上代码仓，派发一次性 `Reader Subagent` 输出带行号对比摘要。

2. **阅读深度动态升档（Dynamic Upgrade）**
   - 若某篇原本仅做 `L0/L1` 阅读的论文成为关键论证支点或潜在理论重叠对象，立即派发 `Paper Reader Subagent` 拉取源码升档至 `L2`（含精读 Appendix 证明与实验）或 `L3` 更新 `notes.md`，并将 `02_paper_map.md` 中的重要相关工作如实同步进 `03_idea_discussion.md`（防跨文档遗忘与稻草人简写）。

---

## 五、讨论节奏与 `03_idea_discussion.md` 维护

1. **严格执行 `Explore` / `Challenge` / `Refine` / `Pivot` 准则**（见 [AGENTS.md](../../AGENTS.md) 第三节）：
   - 面对发散探询（`Explore`），对照地图客观评估利弊，不讨好顺杆爬；
   - 面对根基质疑（`Challenge`），**绝不护短**，立刻回查原文、代码或写简短数值脚本验证质疑是否成立；若核心代理假设尚未经实验证实，如实保留在 `当前工作假设` 中交由后续先导实验检验，严禁用更复杂的形式包装掩盖前提风险。
2. **结构化落盘**：按 `templates/03_idea_discussion.md` 清晰分离 `已验证事实`、`当前工作假设`、`基线纠偏前提 vs. 单一核心机制` 与 `已排除废案归档`。
3. **进入阶段 4**：当研究问题聚焦、核心机制满足极简预算且用户认可时，加载 **阶段 4（`skills/idea-stage4-review-handoff/SKILL.md`）** 启动独立反证审查。
