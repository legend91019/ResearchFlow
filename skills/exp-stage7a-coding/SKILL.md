---
name: exp-stage7a-coding
description: Stage 7A of ResearchFlow Experimentation. Implements modular experiment code reusing official baseline repos, enforces conditional-equivalent hardware adaptation, runs mechanism-aware trigger tests (test_claims.py), a blind Code-to-Claim audit, and a worst-case VRAM/throughput probe before full execution.
---

# Stage 7A — 实验编码、条件等价适配与科学保真预检 (`exp-stage7a-coding`)

本技能承接用户拍板后的 `06_exp_plan.md`、`figures/figure_plan.md` 与 `exp_manifest.json`，在正式启动数小时至数十小时的 GPU 运行前，完成**高保真实验代码构建、显存条件等价适配与三重科学门禁预检**，从源头杜绝“把 Baseline 写弱”、“调小 `batch_size` 意外改变算法动力学”、“开关参数未接通的假消融”以及“跑到第 9 小时才爆显存”。

---

## 一、Step 1：外科手术式基线复用与评测协议锁定

在 `workspaces/<project>/experiments/` 下组织模块化代码（通过命令行参数 `--method`、`--benchmark`、`--seed` 等驱动各原子单元，严禁把所有实验揉成不可拆分的单文件脚本）：

1. **优先复用官方代码库（防从零默写阉割版 Baseline）**：
   - 对照 `papers/<slug>/repo/` 与 `notes.md` 第 6 节代码坐标，优先在主锚点官方代码基础上做最小侵入式扩展；若需将外部 Baseline 接入同一评测框架，必须逐行核对其官方核心函数、归一化、掩码与方法级超参（遵循 `06_exp_plan.md` 锁定的三层参数协议）。
2. **独立只读评测器与数据埋点（Evaluator Lock & Telemetry Hooks）**：
   - 将数据集划分加载、指标计算与失败样本固定分母处理封装在独立的 `eval_harness.py` 中，计算其 SHA-256 写入 `exp_manifest.json` 的 `evaluator_sha256` 字段（后续任何方法代码严禁修改评测器，严禁利用测试集结果调参选模）；
   - 对照 `figures/figure_plan.md` 与 `06_exp_plan.md` 表 B（零算力派生切片），确保运行脚本一次性落盘全部所需的细粒度中间文件（如完整评测矩阵、逐层统计、峰值显存与步耗时）及 `exp_manifest.json` 指定的 `metrics_file` JSON。
3. **长耗时任务级断点支持（按需启用，拒绝过度设计）**：
   - 若单个原子运行单元预计耗时 **`<= 60–90 分钟`**，直接依赖 Stage 7B `run_matrix.py` 的单元级 `ledger.jsonl` 跳过即可，无需写复杂的步级恢复；
   - 若单个原子单元预计耗时 **`> 90 分钟`** 或运行在易被抢占实例上，须在任务/Epoch 边界保存包含模型、优化器、学习率调度器、随机数状态及**算法特有状态（如历史子空间、记忆库、统计矩阵）**的完整训练级 Checkpoint。

---

## 二、Step 2：条件等价的硬件与显存适配（Conditional Equivalence Adaptation）

当目标显卡显存受限时，允许调整物理执行旋钮，但**必须证明没有静默改变算法的数学语义**（“Effective Batch Size 数值相等 $\neq$ 训练过程自动等价”）：

1. **精确整除硬断言**：代码中显式分离科学批大小 `effective_batch_size` 与物理微批 `micro_batch_size`，强制执行：
   ```python
   assert effective_batch_size % (micro_batch_size * num_gpus) == 0
   grad_accum_steps = effective_batch_size // (micro_batch_size * num_gpus)
   ```
2. **算法边界与可分解性核查**：
   - 检查是否存在跨样本批内交互（如 `BatchNorm`、对比学习批内负采样）：若存在，禁止单纯缩小 `micro_batch_size` 充当等价适配；
   - 变长序列（如 LLM 微调）按有效 Token 总数跨累积步正确归一化 Loss，而非对不同长度 micro-batch 的局部均值简单求平均；
   - **梯度裁剪（Gradient Clipping）、协方差/草图累积更新、持续学习梯度投影等钩子必须严格绑在 `optimizer.step()` 有效更新边界上**，严禁误在每个 `backward()` 微步触发！
   - 若采用近似草图或在线低秩截断降低显存，属于算法级近似而非无损硬件旋钮，必须按 `06_exp_plan.md` 的设计配置统一声明。
3. **有损降级红线**：若极限压测仍装不下，确需修改 `effective_batch_size`、`max_seq_len`、数值精度或训练轮数，**必须暂停征得用户同意，并同步更新所有对比方法配置**，绝不允许只对单一方法降格。

---

## 三、Step 3：点火前三重预检门禁（Pre-Flight 3-Gate Check）

在挂载全量运行队列前，依次通过以下三项快速检查（全程约 3–5 分钟）：

1. **门禁 1 — 机制感知最小触发测试（`experiments/tests/test_claims.py`）**：
   - 将 `06_exp_plan.md` 第 5 节声明的触发断言写成可执行的轻量测试脚本并运行通过：
     - 验证核心机制与各消融开关确实在对应环节生效（如投影后正交残差 $\le \epsilon$、单步更新量符合理论性质、第 2 任务记忆激活生效）；
     - 若启用了 `grad_accum_steps > 1`，在同一小批固定数据上核验适配前后 `optimizer.step()` 次数、统计量更新边界及参数更新量在数值容差内一致；
     - 验证单步冒烟后 `metrics_file` 与 `figure_plan.md` 要求的中间数据文件均格式合法且无 `NaN`/`Inf`。
2. **门禁 2 — 历史隔离的 `Code-to-Claim Auditor Subagent`（独立代码盲审）**：
   - 派生一个零编码对话历史的独立子智能体，仅提供 `04_handoff.md`、`06_exp_plan.md` 与 `experiments/` 代码，专项审计：
     - 代码公式、符号方向与缩放系数是否与文档规格完全一致？
     - 有无只给我方方法暗加额外Trick（如独享 warmup、梯度裁剪或特征归一化）而弱化 Baseline？
     - 训练与超参选择代码是否严格隔离了测试集？
   - 发现任何偏差当场修复并重跑 `test_claims.py`。
3. **门禁 3 — 真机稳态吞吐 + 10 秒最坏条件显存压测（Worst-Case Resource Probe）**：
   - 通过 `remote_gpu.py push` 同步代码至目标 GPU 机器，不仅测常规输入的稳态 `ms/step`（跳过前 10 步预热），**还必须构造一个“计划内最坏资源状态”的 10 秒合成压测**（如最大序列长度 `max_seq_len` + 最后一轮最大历史子空间维数 / 最大记忆库容量 / 最高图元数），实测 `worst_case_peak_vram_gb` 与预计磁盘占用，确认全程不会在后期发生 OOM 或爆盘后，正式进入 **阶段 7B（`skills/exp-stage7b-execution/SKILL.md`）**。
