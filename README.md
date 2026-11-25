# ResearchFlow

**ResearchFlow** 是一套运行在原生编码智能体宿主（**Antigravity**、**Claude Code**、**Codex**）之上的 **科研工作空间协议（Research Workspace Protocol）**。

它不重复造笨重脆弱的多智能体运行时，而是专注于解决 AI 辅助科研前期最致命的三个痛点：
1. **文献逐层摘要导致的信息漂移**（用完整保留的原始 LaTeX 源码与代码 + 行号索引 `index.md` + JIT 按需原片加载替代二手知识卡片堆砌）；
2. **检索覆盖盲区与上下文涣散**（用一次性隔离 Subagent 承担脏搜索与长文阅读，结合纵向引文演化、横向异路线、同构机制与**反证/负面结果**四视角深搜，主窗口只保留高信噪比知识状态）；
3. **先射箭后画靶与确认偏误**（严禁未读文献前盲猜创新点与 Benchmark；严格区分作者声称、实验实证、模型推断与未验证假设；移交实验前由零历史包袱的独立 `Critical Reviewer` 执行五问反证与防撞车核查）。

---

## 架构总览

```text
研究者 (Human)  ◄──── 自然对话 · 关键科学决策 · 假设质询 (Challenge) ────►  宿主主 Agent (Host Agent)
                                                                              │
                    ┌─────────────────────────────────────────────────────────┼──────────────────────┐
                    ▼                                                         ▼                      ▼
        协议与阶段技能 (AGENTS.md + skills/)                         隔离任务角色 (Subagents)     确定性辅助脚本 (scripts/)
        - Stage 1: 方向广搜与分类树定界                             - Survey Subagent            - cite_graph.py (S2+OpenAlex 双向引文网)
        - Stage 2: 四视角深搜与动态 L0-L3 建图                      - Deep Search Subagent       - fetch_paper.py (arXiv 原始源码解包
        - Stage 3: 原文/代码切片 JIT 挂载与受约束构思                - Paper Reader Subagent        + LaTeX 拓扑行号索引 + 官方仓浅克隆)
        - Stage 4: 独立反证审查与主实验共识交接                      - Critical Reviewer Subagent
                    │                                                         │                      │
                    └──────────────────────────────┬──────────────────────────┴──────────────────────┘
                                                   ▼
                                项目磁盘：唯一持久化研究状态 (workspaces/<project_slug>/)
                                ├── 01_scope.md             # 学术分类树、时序源流与锁定分支
                                ├── 02_paper_map.md         # A→B→C 演进脉络、机制/混杂对比表、主实验共识
                                ├── 03_idea_discussion.md   # 已验证事实 vs. 工作假设、候选方案、废案归档
                                ├── 04_handoff.md           # 定稿方法规格与近期共识主实验接力包
                                ├── search_logs/            # 检索轨迹、临界淘汰审计表、独立反证报告
                                └── papers/<slug>/          # source/ 原始源码、index.md 行号索引、notes.md、repo/
```

---

## 目录结构

```text
ResearchFlow/
├── AGENTS.md                        # 全局科研认识论、沟通规范、交互状态机与上下文卫生协议
├── CLAUDE.md                        # Claude Code 入口指引（指向 AGENTS.md）
├── skills/                          # 按阶段按需加载的模块化科研技能
│   ├── idea-stage1-landscape/       # 阶段 1：综述优先广搜、方法分类树梳理与细分分支锁定
│   ├── idea-stage2-literature-map/  # 阶段 2：四视角深搜、防漏筛审计、L0-L3 动态分级阅读与建图
│   ├── idea-stage3-ideation/        # 阶段 3：JIT 原文/源码核验、受约束构思与假设质询
│   └── idea-stage4-review-handoff/  # 阶段 4：独立 Critical Reviewer 反证审查与主实验设置交接
├── scripts/                         # 纯 Python 标准库（可选 PyMuPDF 增强）确定性工具
│   ├── cite_graph.py                # Semantic Scholar + OpenAlex 双向引文网络获取与去重导出
│   └── fetch_paper.py               # arXiv e-print 源码无损解包、LaTeX 行号索引生成与 GitHub 代码浅克隆
├── templates/                       # 状态文档与单篇阅读档案模板
├── tests/                           # 辅助脚本完整单元测试
└── workspaces/                      # 实际课题工作目录（默认本地保留，不污染框架仓库）
```

---

## 快速开始

### 1. 环境准备
脚本核心功能仅依赖 **Python >= 3.10 标准库**，开箱即用；如需解析无 LaTeX 源码的纯 PDF 论文，可选安装 `pymupdf`：

```bash
pip install -e ".[pdf,dev]"
```

可选配置环境变量以提高文献 API 速率上限：
- `S2_API_KEY`：Semantic Scholar API Key（未配置时自动降级/联合使用 OpenAlex 免费接口）
- `OPENALEX_EMAIL`：OpenAlex 礼貌池邮箱（提升免费并发配额）

### 2. 在宿主 Agent 中启动课题
用 **Antigravity**、**Claude Code** 或 **Codex** 打开本仓库根目录，直接用自然语言开启研究（支持两种起点）：

- **起点 A：从宽泛大方向起步（走完整阶段 1 → 4）**
  > “我想研究持续学习（Continual Learning）方向，手头算力是单张 24G 显卡，请新建工作空间 `workspaces/cl_peft` 开始阶段 1 广搜调研。”

- **起点 B：手里已有 1–3 篇种子论文（跳过阶段 1 广搜，直入阶段 2 顺藤摸瓜）**
  > “我想围绕 arXiv:2310.06762 (O-LoRA) 所在的细分路线找改进点，算力上限单张 4090，请建工作空间 `workspaces/cl_ortho` 直接初始化范围并进入阶段 2 深搜建图。”

### 3. 命令行脚本独立用法

```bash
# 1) 拉取种子论文的双向引文网络（References + Citations），导出 Markdown 与 JSON
python scripts/cite_graph.py 2310.06762 \
  --direction both \
  --limit 40 \
  --out workspaces/demo/search_logs/olora_citations.md \
  --json-out workspaces/demo/search_logs/olora_citations.json

# 2) 下载 arXiv 原始 LaTeX 源码包解包至 source/，生成章节/公式/表格行号索引 index.md，并浅克隆官方仓库
python scripts/fetch_paper.py \
  --arxiv 2310.06762 \
  --workspace workspaces/demo \
  --slug 2023_olora \
  --repo https://github.com/cmnfriend/O-LoRA \
  --role "Direct Baseline"
```

---

## 设计哲学：阶段交接与防跑偏

- **保持研究目标稳定，而非保护错误假设**：协议明确区分用户的 `Explore`（发散探询，不顺杆爬换主线）、`Challenge`（质疑当前假设或指出混杂解释，严禁护短，立即回查原文控制组）、`Refine`（局部打磨）与 `Pivot`（明确换道）。
- **落盘清窗**：每完成一个阶段（或讨论轮次较长时），所有事实、工作假设与废案原因均保存在 `workspaces/<project>/01~04_*.md` 中，随时可通过 `/compact` 或新开对话窗口零损续接。

---

## License

MIT License
