# 07 Experiment Results & Fidelity Audit — <课题简称>

- **完成日期**：YYYY-MM-DD
- **对应实验计划**：`06_exp_plan.md` | **运行清单**：`experiments/exp_manifest.json`
- **原始账本与审计报告**：`experiments/results/ledger.jsonl` | `experiments/results/audit_report.md`（`audit_exp.py` 状态：`PASS`）
- **实际执行硬件环境**：<显卡型号 × 数量、CUDA/PyTorch 版本、有效运行总卡时>

## 1. 计划覆盖率与代码版本溯源摘要
- **计划运行单元总数**：`<N>` | **有效完成**：`<N>` | **曾触发失效重跑**：`<K>` | **未完成/失败**：`0`
- **有效结果对应的 Git Commit**：`<commit_sha>` | **冻结评测器哈希**：`<evaluator_sha256>`
- **执行过程中的工程/环境自愈记录（Ⅰ/Ⅱ 类故障透明披露）**：...

## 2. 主实验结果（Main Comparison）
> 关键汇总数值建议附 `<!-- @evidence:experiments/results/...#key -->` 供 `audit_exp.py` 自动溯源核验。

| 方法 | Benchmark 1（主指标 / 权衡指标） | Benchmark 2（主指标 / 权衡指标） | 备注（超参协议/种子数） |
| :--- | :---: | :---: | :--- |
| `Baseline-Clean` | ... | ... | ... |
| ... | ... | ... | ... |
| **`Ours`** | **`78.46` <!-- @evidence:experiments/results/summary.json#ours.b1_aa -->** | ... | ... |

- **主表核心实证结论**：...

## 3. 去混杂消融与反事实对照结果（Ablations & Counter-Variants）

| 变体名称 | 相对完整版的改动 | 核心指标 | 权衡指标 | 因果归因解读 |
| :--- | :--- | :---: | :---: | :--- |
| ... | ... | ... | ... | ... |

## 4. 机制诊断、敏感度与工程开销实测（Mechanism, Sensitivity & Overhead）
- **内部机制与权衡探针发现**：...
- **超参敏感度与规模/序列鲁棒性**：...
- **全口径计算、显存与存储开销对账表**：

| 方法 | 训练步耗时 (`ms/step`) | 额外阶段开销 (`s`) | 峰值显存 (`GB`) | 额外参数/存储 (`MB`) |
| :--- | :---: | :---: | :---: | :---: |
| ... | ... | ... | ... | ... |

## 5. 负面结果、适用边界与异常诚实披露（Negative Findings & Boundaries）
> 严禁隐瞒不利数据或私自删改条件；如某变体在特定边界下退化，或极简变体优于复杂版，须在此完整报告供研究者决策：
- ...

## 6. 已产出的实验图表索引（详见 `figures/` 与 `figures/figure_plan.md`）
- `figures/fig_e1.pdf` (`.png`)：<对应结论简述>
- `figures/fig_e2.pdf` (`.png`)：<对应结论简述>
