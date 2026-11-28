---
name: exp-stage5-pilot
description: Stage 5 of ResearchFlow Experimentation. Pauses to confirm pilot compute (never silently running on the local host), executes the 1-3h Gate 0 Pilot Falsification Test via remote_gpu.py, logs baseline throughput/VRAM telemetry, and locks the parsimonious method specification in 05_pilot_report.md.
---

# Stage 5 — `Gate 0` 先导实证与方法定型 (`exp-stage5-pilot`)

在投入数十卡时构建全套主实验与消融矩阵之前，本技能承接 `04_handoff.md` 第 3 节，在真实底座模型与代表数据上用 **最小算力（通常单卡 1–3 小时）** 完成核心工作假设的**生死证伪**与**奥卡姆实战减法**，顺手测准真机吞吐率与显存基线，产出 `05_pilot_report.md`。

---

## 一、Step 1：算力前置确认（⏸️ 强制停顿节点 — 严禁擅跑宿主本机）

1. 读取 `workspaces/<project>/04_handoff.md`（重点核对第 2 节核心公式/代码坐标与第 3 节 `Gate 0` 最小设置及 Go/No-Go 门槛）与 `03_idea_discussion.md`。
2. **算力边界铁律**：
   - **严禁未经用户明确授权直接在宿主本机（Host CPU 或本机 GPU）上运行模型训练、推理或下载大模型权重**！
   - 除非用户在**当前指令**中已经明确提供了本次 `Gate 0` 的远程 SSH 连接信息（或明确指示使用已初始化的 `.remote_host.json` / 指定本机设备），否则**必须先停下来向用户简明汇报 `Gate 0` 拟跑的模型、对照项与预计时长（1–3 小时），询问本次小型先导实验使用的计算资源（如远程 GPU SSH 串与密码/密钥）**。

---

## 二、Step 2：远程环境初始化与先导代码构建

拿到用户确认的计算资源后，在 `workspaces/<project>/gate0_pilot/` 下构建最小可复现实验包：

1. **免转义连接与硬件探针**（使用零依赖工具 `scripts/remote_gpu.py`，免手搓密码转义）：
   ```bash
   # 首次绑定（通过环境变量或 stdin 一次性注入 Ed25519 公钥，绝不落盘明文密码）
   python scripts/remote_gpu.py init --workspace workspaces/<project> --ssh "ssh -p <port> <user>@<host>" --password-env RF_SSH_PASS
   # 核验显卡型号、显存、根盘 '/' 与数据盘（如 /root/autodl-tmp）剩余空间及 PyTorch/CUDA 环境
   python scripts/remote_gpu.py probe --workspace workspaces/<project>
   ```
2. **先导对照设计准则（防混杂 & 顺手产出动机证据）**：
   - 紧扣 `04_handoff.md` 第 3 节，构造 **2×2 正交受控对照**或**极简组件剥离对照**（例如：`Baseline-Clean` vs. `单原语极简变体` vs. `完整候选变体`），确保能单独拆出核心算子的净效应，排除步长调度、学习率量级或参数量混杂；
   - 若核心故事包含“前人基线存在某种几何/统计退化现象”，在 `Gate 0` 中同步记录该现象的定量诊断指标（可直接复用于后续论文引言/方法前导章节的**动机探针图**）。
3. **点火前两步快检**：
   - **代数/梯度单元测试**：编写极简测试验证核心算子数学性质（如正交性、等距性、边界非 `NaN`）；
   - **15 秒真机冒烟与吞吐标定**：跳过前 5–10 步编译/预热后，实测并记录真实底座上的 **`steady_ms_per_step`**、**后处理耗时**与 **`peak_vram_gb`**（这组实测硬件数据将作为 Stage 6 全量实验估时的基准锚点）。

---

## 三、Step 3：后台守护运行与非轮询巡检

1. 通过 `remote_gpu.py push` 秒传代码，并用 `remote_gpu.py launch` 挂入远端独立会话组后台运行（自动将 `HF_HOME` / `MODELSCOPE_CACHE` / `TORCH_HOME` 重定向至数据盘，防止撑爆 `/` 根分区）：
   ```bash
   python scripts/remote_gpu.py push --workspace workspaces/<project> --src gate0_pilot
   python scripts/remote_gpu.py launch --workspace workspaces/<project> --job-id gate0 --workdir gate0_pilot --gpu 0 --cmd "python run_gate0.py"
   ```
2. **严禁在循环中刷屏轮询**：先在开跑 5–10 分钟后做一次单次快照检查确认首轮正常落盘，随后使用宿主原生定时唤醒（或按预计耗时分段检查）执行：
   ```bash
   python scripts/remote_gpu.py status --workspace workspaces/<project> --job-id gate0 --progress-file gate0_pilot/results/progress.json
   ```
   若发现 `RUNNING` 状态下长期极低 GPU 利用率且进度停滞，调用 `remote_gpu.py profile --job-id gate0` 抓取实时调用栈排查 CPU 算子瓶颈（如冗余全矩阵分解或逐条分词），修复向量化后从已完成单元无缝续跑。
3. 运行结束后，执行 `remote_gpu.py pull` 将 `gate0_pilot/results/` 完整拉回本地工作区归档。

---

## 四、Step 4：实证裁决与方法定型（⏸️ 强制停顿节点）

参照 `templates/05_pilot_report.md` 如实撰写 `workspaces/<project>/05_pilot_report.md`（严禁报喜不报忧），给出三选一裁决并**暂停等待用户拍板**：
- **`GO`（原方案验证通过）**：核心假设与量化门槛全部达标，锁定当前规格进入 Stage 6；
- **`SIMPLIFY / REFINE`（奥卡姆实战减法锁定更优变体）**：若实测发现**去掉某附加子模块后的极简变体效果更优或持平**，优先锁定极简变体作为主方法（同步更新 `04_handoff.md` 主线规格）；
- **`PIVOT`（核心假设证伪）**：诚实报告失效原因与排除证据，建议回退 `skills/idea-stage3-ideation/SKILL.md` 调整方向，绝不硬着头皮进入主实验烧卡。
