# Paper Note: <Title>

- **Slug**: `<slug>`
- **Authors / Year / Venue**: <Authors> (<Year>, <Venue / arXiv ID>)
- **Identifier**: arXiv:`<id>` | DOI:`<doi>`
- **Official Repo**: <URL or None> (commit: `<sha or N/A>`)
- **Role**: `Direct Baseline` / `Recent Frontier` / `Foundational` / `Counter-Evidence` / `Cross-Domain`
- **Reading Depth**: `L0 (Screened)` / `L1 (Mechanism & Main Table)` / `L2 (Full Text & Appendix)` / `L3 (Code Audited)`

## 1. Research Question & Lineage Position
- **核心问题**：这篇论文具体针对什么问题或前人哪篇工作的什么缺陷？
- **演化链位置**：相对于前作改了什么？后续工作又是如何评价或跟进它的？

## 2. Core Mechanism（原样保留关键数学形式）
> 写出核心定义、目标函数或更新规则，**必须标注原始源码文件与行号坐标**（如 `source/sections/method.tex:L110-L148`），并解释关键符号定义（核对 `macros.tex`）。

## 3. Explicit & Implicit Assumptions
- **显式假设**：论文明确声明的前提条件。
- **隐式假设**：`[模型推断]` 论文在推导或实现中默认成立、但未明说或未必普适的条件。

## 4. Author Claims vs. Actual Experimental Evidence
- **`[作者声称]`**：作者将性能提升归因于什么机制？
- **`[实验实证]`**：主实验和消融实验**实际控制并证明**了什么？（附 `source/...` 表格与附录坐标）
- **未控制的混杂因素**：实验对比中是否存在未对齐的变量（如有效步长、额外内存/算力开销、特定超参调优、数据泄漏风险等）？

## 5. Unverified Claims & Limitations
- 论文自身承认的局限 + 阅读发现的尚未验证主张或失效边界。

## 6. Code Mapping（L3 代码审计必填；L1/L2 写“当前未升至 L3”）
- **核心算法实现位置**：`repo/<path>:Lxx-Lyy`（说明函数职责，核对代码实现是否与论文公式完全一致，有无论文未提的工程 trick）
- **实验配置与超参位置**：`repo/<path>:Lxx-Lyy`

## 7. Potential Research Questions Triggered
- 基于上述实证缺口或隐式假设，值得追问的 1–2 个具体科学问题。
