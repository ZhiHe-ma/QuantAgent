# Compatibility Test Matrix

| 层级 | 组合 | 当前证据 |
| --- | --- | --- |
| 单插件 | JSON source 1.0.0 | UTF-8 读取、对象/数组归一、目录限制、大小限制 |
| 单插件 | SQLite source 1.0.0 | `mode=ro`、表存在检查、JSON 列解码、数量上限 |
| 单插件 | Signal quality 1.0.0 | 缺失、重复 ID、无效或无时区时间、空数据 |
| 单插件 | Markdown report 1.0.0 | 仅写运行目录，显示范围和未评价项 |
| 单插件 | Packet replay 1.0.0 | 验证契约与内容哈希，篡改包失败关闭 |
| 单插件 | Outcome evaluator 1.0.0 | 24/72/168 自然小时、延迟限制、不可评价原因 |
| 单插件 | SQLite outcome writer 1.0.0 | 默认预览、显式写根、幂等、冲突事务回滚、单位转换 |
| 单插件 | Outcome report 1.0.0 | 可评价/不可评价分列，展示口径和范围 |
| 单插件 | Daily context source 1.0.0 | JSON 大小、日期、指标、记忆与因子结构校验 |
| 单插件 | Replay daily analysis 1.0.0 | 固定 UTF-8 分析、空内容拒绝、来源哈希 |
| 单插件 | DeepSeek daily analysis 1.0.0 experimental | 模拟传输、响应结构、密钥不落盘、联网与权限拒绝 |
| 单插件 | Daily Markdown report 1.0.0 | 与现有生产日报共用提示词和渲染函数 |
| 单插件 | Qlib factor research 1.0.0 experimental | 普通 CI 验证子进程协议、权限、路径、错误隔离；真实 Qlib 需显式环境测试 |
| 单插件 | Factor research report 1.0.0 | 记录输入哈希、精确运行时版本、IC/Rank IC 与能力边界 |
| 单插件 | bt portfolio backtest 1.0.0 experimental | 普通 CI 验证协议、显式进程权限、下一根 bar 延迟和失败关闭；真实 bt 需显式环境测试 |
| 单插件 | Backtest report 1.0.0 | 展示时间/价格语义、成本、策略与等权基线、精确版本和能力边界 |
| 连接处 | source → quality | `quantagent.signal_history.v1` |
| 连接处 | quality → report | `quantagent.data_quality.v1` |
| 整套配方 | JSON → quality → report | 固定样本离线通过 |
| 整套配方 | SQLite → quality → report | 临时数据库离线通过 |
| 整套配方 | packet replay → outcome → SQLite preview/apply → report | 固定价格样本离线通过 |
| 整套配方 | daily JSON → replay analysis → Markdown report | 固定上下文与分析样本离线通过 |
| 整套配方 | CSV → Qlib StaticDataLoader → factor report | 固定 20 行样本；真实结果仅在 `QUANTAGENT_QLIB_PYTHON` 集成测试通过时成立 |
| 整套配方 | CSV → bt portfolio backtest → report | 固定 30 行合成面板；信号延迟 1 bar，手续费 5 bps，滑点 5 bps，含等权基线 |
| 安全边界 | 路径越界、权限不足、未知插件 | 失败关闭并记录或在执行前拒绝 |
| Agent 入口 | data-health Agent → signal-data-health Skill → historical-data-health Recipe | 精确版本和 SHA-256；与直接 Recipe 共用 RecipeRunner、权限预检及步骤语义；Agent 身份写入 `run.json` |
| Agent 安全边界 | 不安全 YAML、目录/Skill 篡改、未知版本/Recipe/能力/绑定、非 verified 状态 | 创建运行目录前失败关闭 |

CI 在 `ubuntu-latest` 和 `windows-latest` 的 Python 3.12 上运行完整离线 unittest。Qlib 与 `bt` 的普通 CI 使用协议 worker，不导入重型依赖；可选集成测试必须指向独立安装的 Python，并在结果包记录上游及 pandas 等精确版本。真实外部接口仍须单独报告。

## P0/P1 Agent/Skill 矩阵（2026-09-22）

P0 规范仍是语义基线；P1 只把单一确定性数据体检 Agent 推进到 `offline_fixture`，其余条目保持 `static`。

| 测试面 | P0 产物 | P1 当前证据 | P2/后续必须补的行为证据 |
| --- | --- | --- | --- |
| AgentManifest 结构 | Draft 2020-12 Schema、精确 ID/版本、模型能力、预算、审查和空 `callable_agents` | 严格 SafeLoader 拒绝锚点、别名、显式标签、merge key 和重复键；Schema、目录哈希和精确引用已实测 | 签名发布、目录迁移和更多清单版本 |
| SkillManifest 结构 | 来源 commit/许可证、文件哈希、契约、能力、配方和测试状态 | `builtin.signal-data-health@1.0.0` 已打包；Schema、路径限制、逐文件/包哈希及篡改拒绝已覆盖 | 第三方包签名、NOTICE 聚合和安全审查流水线 |
| Agent → Skill → Recipe | 双向精确允许名单；共用现有 RecipeRunner | 单一 verified 组合通过；未知版本、越权 Recipe、额外能力和非 verified 状态失败关闭 | 多 Skill 选择与真正研究型 Agent |
| 模型能力协商 | 文本、结构化输出、工具调用、上下文和离线回放分开声明 | 无模型 Skill 的静态能力相容检查已实现；未选择或调用模型 | 能力不足拒绝、允许名单替换、实际模型/Prompt/费用落盘 |
| 权限交集 | 用户、部署、Agent、Recipe/Plugin、凭据范围取交集 | Agent 入口复用 RecipeRunner 的插件权限、离线和绑定预检 | 部署策略、凭据范围、工具调用/墙钟/费用动态计量 |
| 研究契约 | request、evidence、thesis、handoff 的语义边界 | 字段语义已定义；实例 Schema 未实现 | 时间/单位/来源/缺失/Point-in-Time 正反例和血缘校验 |
| 注入与交接 | 不可信文字不得成为工具或 handoff；首版不启用交接 | 边界已定义；Router 未实现 | 伪造工具 JSON、越权目标、循环、重复和预算增加拒绝 |
| thesis-tracker | 首个 Skill 的输入输出与 Crypto 边界 | 目标已定义；尚未移植 | 固定夹具可重放、支持/反对证据、修订幂等、Daily/Monitor 回归 |

## 本次 P0 基线复跑（2026-09-22）

基线提交 `12407081cb882ae526180145237f32093f83dffc` 在 Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下运行 `python -m unittest discover -s tests -v`：共运行 81 个测试，其中 79 个通过、0 个失败、2 个跳过。P0 变更后的完整回归共运行 86 个测试，其中 84 个通过、0 个失败、2 个跳过。跳过项都是未配置专用解释器的真实 Qlib 与 bt 测试；历史真实依赖记录没有被冒充成本次复验。固定 tree、环境和夹具哈希见 `docs/P0_BASELINE_REPORT.md`。

## P1 Agent 入口本地回归（2026-09-22）

Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下完整运行 96 个测试：94 个通过、0 个失败、2 个跳过。P1 新增行为测试验证精确目录解析、Agent 与直接 Recipe 的同一运行器/步骤语义、审计身份、目录重复键、清单和 Skill 内容篡改、未知版本/Recipe/绑定、额外能力、非 verified 状态、模型需求、不安全/非 JSON YAML，以及非法审计上下文在创建运行目录前被拒绝。两个跳过项仍是未配置专用解释器的真实 Qlib 与 bt 测试，未被并入通过数。

## Qlib 本地受控验证（2026-09-21）

| 平台 | 组合 | 固定样本结果 | 结论 |
| --- | --- | --- | --- |
| Windows | Python 3.12.8 + pyqlib 0.9.7 + pandas 3.0.6 | `StaticDataLoader` 读取 20 行、5 标的、4 日期；4 个日期均可计算 IC/Rank IC；输入哈希与版本已落盘 | 此组合的固定样本兼容测试通过；插件仍为 `experimental` |

该验证未使用 Qlib 行情供应商数据，未初始化 provider、训练模型或运行回测。第一次真实测试暴露了子进程最小环境缺少用户目录变量的问题；补回 `HOME`/Windows 用户目录定位变量后通过，API key 等非白名单变量仍不传给 worker。

## bt 本地受控验证（2026-09-21）

| 平台 | 组合 | 固定样本结果 | 结论 |
| --- | --- | --- | --- |
| Windows | Python 3.12.8 + bt 1.2.3 + ffn 1.2.2 + pandas 3.0.6 | 30 行、3 标的、10 时间点；信号延迟 1 bar；总成本 10 bps；策略总收益 2.9569%，等权基线 9.6667% | 接口与假设落盘通过，且样本策略明显跑输基线；插件仍为 `experimental` |

该结果诚实保留负面的相对基线差异，目的只是证明适配器没有挑选“看起来赚钱”的验收样本。样本为合成价格，不验证真实复权、交易日、流动性、容量或订单成交。

未覆盖：真实 DeepSeek 外部联调、在线数据源、Qlib 供应商数据、Qlib 模型训练、真实行情回测语义、模型驱动 Agent、`thesis-tracker`、动态工具调用/墙钟/费用限制、人工暂停恢复、Tool Broker、Typed Handoff、OpenStock API/UI、MLflow、Pandera、容器/操作系统级隔离、多来源实盘对账、模型收益评价和实盘交易。
