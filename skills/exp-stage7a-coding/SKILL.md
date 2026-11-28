---
name: exp-stage7a-coding
description: Stage 7A of ResearchFlow Experimentation. Enforces modular plugin coding (no monolithic God-scripts), verified asset paths, 4D device-agnostic resource hygiene (VRAM/RAM/Disk/tmpfs/Operator latency), anti-regression bugfix checks, real-data all-branch smoke probes via remote_gpu.py exec, and a final-lock Code-to-Claim blind audit.
---

# Stage 7A — 模块化实验编码、四维资源护栏与终锁盲审 (`exp-stage7a-coding`)

本技能承接用户确认后的 `06_exp_plan.md`、`figures/figure_plan.md` 与 `exp_manifest.json`，负责编写健壮的实验与绘图代码，并在正式挂起长耗时实验前完成**本地机制/异常单测 → 远端真数据全分支 2 步冒烟与四维资源体检 → 最终锁版独立代码盲审**。

> **关键顺序铁律**：**独立代码盲审（Gate 3）必须放在所有真机适配与性能优化彻底改定型之后的最后一刻执行！** 严禁“先做完代码盲审，后面又为了压时间或修 OOM 大改几百行代码直接脱审上线”。

---

## 一、Step 1：模块化插件架构与零幻觉资产准备（防巨石代码“改 A 坏 B”）

1. **严禁编写上千行 `if/elif` 单文件大泥球（Modular Plugin Isolation）**：
   当对比多个 Baseline 与消融变体时，必须按职责解耦目录结构，避免改一个基线的内存逻辑把其他方法改崩：
   - `experiments/eval_harness.py`：只读评测器、确定性训练/验证切分与统一口径指标计算（SHA-256 写入 `exp_manifest.json`，严禁触碰测试集调参）；
   - `experiments/runner.py`：共享训练循环、条件等价微批累积、OOM 退避与检查点管理；
   - `experiments/methods/<method_family>.py`：各对比基线与我方变体的独立实现（对照 `papers/<slug>/repo/` 官方源码逐行核对，通过统一钩子接口接入 `runner.py`）；
   - `experiments/plots/`：读取 `results/` 原始 JSON/CSV/NPZ 的确定性制表与绘图脚本（严禁硬编码结果数字）。
2. **严禁瞎猜外部下载源与手搓脆弱底层轮子**：
   - **数据源唯一事实核验**：优先直接打包同步本地 `papers/<slug>/repo/` 中已有的数据集，或使用 `stage6_exp_conventions.md` 已验证的官方归档包；**绝对禁止凭记忆编造未经验证的 HuggingFace 数据集 ID，绝对禁止用 `try/except: pass` 静默吞掉下载失败放空目录过检**（资产准备脚本末尾必须对所有数据集文件非空做硬断言）；
   - **优先调用原生库成熟参数**：优化推理/生成吞吐时（如按长度分桶、早停词、省预填充显存），优先查阅并使用框架原生支持参数（如 `logits_to_keep=1`），避免从零手写自定义解码循环踩远端 `transformers` 新版本接口差异或模型专属 `generation_config`（如默认 `repetition_penalty`）暗坑。

---

## 二、Step 2：跨设备通用“四维资源护栏”与条件等价适配

无论目标机器是 24GB 消费卡、48GB 工作站卡还是 80GB 集群卡，编码时必须同时兜住 **四个物理维度**：

1. **维度 1 — GPU 显存与条件等价微批适配**：
   - 强制断言 `assert effective_batch_size % (micro_batch_size * num_gpus) == 0`；变长序列按全局有效批总监督词元数精确归一化 Loss；梯度裁剪、协方差/草图累积与投影严格绑定在 `optimizer.step()` 有效步边界；
   - 注意分配器兼容性：若某特殊批次调用 `torch.cuda.set_per_process_memory_fraction(...)`，须在 `exp_manifest.json` 对应条目的 `"env": {"PYTORCH_ALLOC_CONF": ""}` 中关闭 `expandable_segments` 防底层冲突；
   - 所有评测入口（含 `Zero-Shot`、`MTL` 等特殊分支）统一包裹自动降批 OOM 保护。
2. **维度 2 — 主机物理内存（Host CPU RAM `RSS`）防强杀**：
   - 大模型权重 CPU 备份、全协方差或对角 Fisher 矩阵极易撑爆 32–64GB 主机内存触发 Linux `OOM-Killer`！对重型矩阵优先采用分块流式计算；切勿对 `mmap` 张量调用 `.clone()` 拉回匿名内存；若为重型方法释放了 CPU 初始权重备份，外层重试逻辑必须检查备份存在性（防 `KeyError` 或拿脏权重重跑）。
3. **维度 3 — 磁盘空间与 `/tmp` 内存盘隔离**：
   - 远端机器根分区 `/` 常不足 30GB，且 `/tmp` 常为 RAM 挂载的 `tmpfs` 内存盘！统一使用 `remote_gpu.py`（已自动将 `TMPDIR`、`HF_HOME`、`MODELSCOPE_CACHE`、`TORCH_HOME`、`PIP_CACHE_DIR` 重定向至大容量数据目录）；
   - 模型权重只保留单一共享副本（过滤冗余 `.pth`/`.bin` 重复格式）；仅对单次耗时 `> 60–90 分钟` 的长序列开启任务级断点（采用 `.tmp` 原子覆写单份最新断点，严禁每跑一组存一份十几 GB 完整模型撑爆硬盘）。
4. **维度 4 — 重型 Baseline 后处理算子耗时防卡死**：
   - 严禁未经测速把大矩阵特征分解（如 `[14336, 14336] eigh`）丢给少核 CPU 死算，也严禁把几万个微小矩阵逐一调 GPU `cusolver` 承受同步延迟，或让 CPU 每步流式拷十几 GB Fisher 导致 GPU 利用率跌破 `20%`！按矩阵规模合理放置设备（大矩阵乘法/大分解上 GPU 逐流执行后立即释放显存，极小秩矩阵走亚毫秒 CPU LAPACK）。

---

## 三、Step 3：防“改 A 坏 B”铁律与三重递进预检门禁

> **反慢速试错铁律**：调试任何单个算子、库接口或显存边界时，**必须使用 `python scripts/remote_gpu.py exec --workspace ... --script quick_check.py` 跑 5–10 秒的同步单点快检**！绝对禁止每改两行代码就盲目挂起一个十几分钟的多模型大脚本靠定时器反复试错！

### 每次修改/提速/修 Bug 必过的“防改 A 坏 B”三项回归锁
凡对代码做性能优化、内存裁剪或 Bug 修复，落盘前必须核查：
1. **跨方法指标口径与数值等价锁**：加速手段（如跳格评测 `diag_last`、批内长度分桶）是否改变了任何指标（如遗忘率 `Fgt`）的数学定义？数据字典键名（如原始 `"prompt"` vs 预分词键）与模型输出前导换行符（如代码补全首字符 `\n`）是否在真实样本上实测非空？
2. **异常恢复路径注入锁**：不能只测正常路径！必须用 `unittest.mock` 人为抛一次 `OutOfMemoryError` 验证降批重试包装器自身不会因语法捕获顺序（如 `except TypeError:` 内嵌套抛错）或缺失字典键而崩溃。
3. **下游图表与清单同步锁**：凡改动 `eval_harness.py` 或输出字段，立即重生成 `exp_manifest.json`（刷新 `evaluator_sha256`）并干跑全部 `plots/*.py` 与制表脚本验证零断链。

---

### 点火前依次通过的三道门禁（Gate 1 → Gate 2 → Gate 3）

1. **门禁 1 — 本地机制、真实样本 Schema 与异常注入测试（`experiments/tests/test_claims.py`）**：
   - 覆盖 `06_exp_plan.md` 声明的核心代数/梯度触发断言、`grad_accum` 条件等价断言、**真实数据集样本格式解析断言**、**模拟 OOM 异常自愈断言**，以及 `audit_exp.py` 绘图脚本反硬编码 AST 扫描。
2. **门禁 2 — 远端真机“全方法分支 2 步真数据冒烟”与四维资源探针**：
   - 用 `remote_gpu.py probe` 与 `remote_gpu.py push` 部署远端环境和数据集（硬断言所有数据集文件非空）；
   - 通过 `remote_gpu.py exec` 在真实底座与真实样本上，对**清单涉及的每一个方法分支与特殊运行模式（含 `Ours`、最吃显存/算力的重型 `Baseline/Oracle`、特殊显存认证分支等）各跑 2 步训练 + 1 次任务切换算子 + 1 小批评测**，同时记录最坏序列/状态下的 **`worst_case_peak_vram_gb`、`peak_cpu_rss_gb`、磁盘余量与各方法算子耗时**；
   - *(可选)* 若用户在 Stage 6 提出了明确的时间预算上限，在此处用实测各环节秒数乘以 `exp_manifest.json` 精确调用次数核验总时长（若超支，先向用户汇报透明裁剪选项，获批后再调整清单）。
3. **门禁 3（最终锁版门禁！）— 历史隔离的 `Code-to-Claim & Regression Blind Auditor Subagent`**：
   - **仅当门禁 1 与门禁 2 全部通过、所有性能与显存代码彻底改定型不再变动后**，派生零编码对话历史的独立子智能体，对照 `04_handoff.md`、`06_exp_plan.md`、`figure_plan.md` 全面盲审最终代码（公式符号一致性、三层超参公平性、测试集物理隔离、异常恢复分支完备性、全套表格与图片字段绑定无遗漏），写入 `search_logs/stage7a_code_audit.md`。
   - 清零所有阻断项并重跑 `test_claims.py` 全绿后，正式进入 **Stage 7B（`skills/exp-stage7b-execution/SKILL.md`）**。
