# Search & Screening Audit — <Stage / Round>

- **执行时间**：YYYY-MM-DD
- **目标范围**：<对应 `01_scope.md` 或具体核查问题（如有 `--before-date` 时间截断在此注明）>

## 1. 多维检索与二跳雷达轨迹
| 检索通道 | 查询词 / 命令参数 | 数据源 | 召回概览与局限说明 |
| :--- | :--- | :--- | :--- |
| **纵向（三桶均衡引文网）** | `cite_graph.py <id> --direction both ...` | S2 + OpenAlex | ... |
| **零延迟新预印本流** | `cite_graph.py --arxiv-recent "..." --days 30` | arXiv API | ... |
| **横向（同问题异路线 & 多渠道）** | ...（含同义词扩展） | Web / OpenReview (含 Workshop) / Anthology | ... |
| **机制（相邻与正逆对偶算子）** | ... | Web / arXiv | ... |
| **反证（负面/复现/失效分析）** | ... | Web / arXiv / OpenReview | ... |
| **本地二跳共引雷达** | `cite_graph.py --scan-bib workspaces/<project>` | 本地 `papers/*/source/*.bib` | ... |

## 2. 入选进入论文地图清单（Selected Papers）
| Slug / ID | 年份 | 标题 | 拟定初始等级 (L1/L2/L3) | 入选理由 |
| :--- | :--- | :--- | :--- | :--- |
| ... | ... | ... | ... | ... |

## 3. 临界淘汰审计表（Borderline Excluded — 重点复核防漏筛）
> 列出相关性排在临界线附近、暂不纳入核心池的前 5–10 篇论文（注意：同赛道近 3–6 个月新预印本严禁仅凭摘要轻易淘汰）：

| 年份 | 标题与标识 (arXiv/DOI/OpenReview) | 未纳入原因（一句话） |
| :--- | :--- | :--- |
| ... | ... | ... |
