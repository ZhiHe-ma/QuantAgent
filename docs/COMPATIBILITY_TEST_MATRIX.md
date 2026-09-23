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
| 单插件 | Thesis review JSON source 1.0.0 | 严格 JSON、Schema、对象哈希、标的、Point-in-Time 截止和显式读取根 |
| 单插件 | Deterministic thesis tracker 1.0.0 | 证据 ID 去重/冲突拒绝、支持/反对/背景分区、claim 和失效条件派生、重复应用幂等 |
| 单插件 | Thesis Markdown report 1.0.0 | 仅写运行目录；不渲染原始不可信证据摘录；固定输入生成固定内容哈希 |
| 连接处 | source → quality | `quantagent.signal_history.v1` |
| 连接处 | quality → report | `quantagent.data_quality.v1` |
| 连接处 | thesis source → tracker → report | `quantagent.thesis_review_input.v1` → `quantagent.thesis_state.v1` → `quantagent.report.v1` |
| 整套配方 | JSON → quality → report | 固定样本离线通过 |
| 整套配方 | SQLite → quality → report | 临时数据库离线通过 |
| 整套配方 | packet replay → outcome → SQLite preview/apply → report | 固定价格样本离线通过 |
| 整套配方 | daily JSON → replay analysis → Markdown report | 固定上下文与分析样本离线通过 |
| 整套配方 | CSV → Qlib StaticDataLoader → factor report | 固定 20 行样本；真实结果仅在 `QUANTAGENT_QLIB_PYTHON` 集成测试通过时成立 |
| 整套配方 | CSV → bt portfolio backtest → report | 固定 30 行合成面板；信号延迟 1 bar，手续费 5 bps，滑点 5 bps，含等权基线 |
| 整套配方 | old thesis + evidence bundle → thesis update → report | 合成 BTC Golden Fixture；正反证据、来源分离、失效条件、血缘、幂等和不可信文本隔离通过 |
| 安全边界 | 路径越界、权限不足、未知插件 | 失败关闭并记录或在执行前拒绝 |
| Agent 入口 | data-health Agent → signal-data-health Skill → historical-data-health Recipe | 精确版本和 SHA-256；与直接 Recipe 共用 RecipeRunner、权限预检及步骤语义；Agent 身份写入 `run.json` |
| Agent 入口 | research Agent → adapted thesis-tracker Skill → thesis-tracker Recipe | 固定版本和 SHA-256；Reader/Analyst/Writer 最小权限；无模型、网络、交易权限或 Agent 间调用 |
| Agent 安全边界 | 不安全 YAML、目录/Skill 篡改、未知版本/Recipe/能力/绑定、非 verified 状态 | 创建运行目录前失败关闭 |
| 研究契约安全边界 | 未来信息、内容篡改、标的不一致、未知字段、额外能力、伪造派生状态、证据 ID 冲突 | 严格失败关闭；prompt-like 证据文本保持为数据，不能改绑定或权限 |
| 只读 API | 既有运行包 → 脱敏摘要/Markdown 报告 | `quantagent.read_api.run_summary.v1` Schema、Bearer、ETag、重复 GET 无写入；不创建或重跑任务 |
| API 安全边界 | 无/错 token、非法运行 ID、跨 subject、路径/符号链接、包或报告篡改 | 401/403/404/409 失败关闭；存储目录被忽略并重新锚定；公共错误不暴露 token、本地路径、原始证据或错误消息 |
| 受控提交 API | 本机登记 thesis 夹具 → 固定离线 Agent → 既有只读摘要/报告 | 显式启用、Bearer、严格正文与夹具哈希、幂等键、并发重复提交只执行一次；拒绝客户端路径/额外能力与运行根目录内输入 |
| 协作取消内核 | 可信调用方 → RecipeRunner/AgentRuntime → 步骤边界 | 开始前或步骤间取消分别落盘为 `cancelled`，保留既成步骤；无效/异常回调失败关闭；未接入 HTTP，也不支持插件内强停 |

CI 在 `ubuntu-latest` 和 `windows-latest` 的 Python 3.12 上运行完整离线 unittest。Qlib 与 `bt` 的普通 CI 使用协议 worker，不导入重型依赖；可选集成测试必须指向独立安装的 Python，并在结果包记录上游及 pandas 等精确版本。真实外部接口仍须单独报告。

## P0/P1/P2 Agent/Skill 矩阵（2026-09-22）

P0 规范仍是语义基线；P1 把确定性数据体检 Agent 推进到 `offline_fixture`，P2 又把离线观点跟踪 Agent/Skill 推进到固定夹具验证。两者是独立目录项，不启用 Agent 间调用。

| 测试面 | P0 产物 | P1/P2 当前证据 | 后续必须补的行为证据 |
| --- | --- | --- | --- |
| AgentManifest 结构 | Draft 2020-12 Schema、精确 ID/版本、模型能力、预算、审查和空 `callable_agents` | 严格 SafeLoader 拒绝锚点、别名、显式标签、merge key 和重复键；Schema、目录哈希和精确引用已实测 | 签名发布、目录迁移和更多清单版本 |
| SkillManifest 结构 | 来源 commit/许可证、文件哈希、契约、能力、配方和测试状态 | 内置数据体检和 Apache-2.0 改编观点跟踪 Skill 已打包；固定上游 commit/blob、完整许可证、NOTICE、逐文件/包哈希及篡改拒绝已覆盖 | 第三方包签名、NOTICE 自动聚合和安全审查流水线 |
| Agent → Skill → Recipe | 双向精确允许名单；共用现有 RecipeRunner | 两个各自固定的 verified 组合通过；未知版本、越权 Recipe、额外能力和非 verified 状态失败关闭 | 受控多 Skill 选择与模型能力协商 |
| 模型能力协商 | 文本、结构化输出、工具调用、上下文和离线回放分开声明 | 无模型 Skill 的静态能力相容检查已实现；未选择或调用模型 | 能力不足拒绝、允许名单替换、实际模型/Prompt/费用落盘 |
| 权限交集 | 用户、部署、Agent、Recipe/Plugin、凭据范围取交集 | Agent 入口复用 RecipeRunner 的插件权限、离线和绑定预检；观点 Reader/Analyst/Writer 权限分别为只读/无权限/仅写运行目录 | 部署策略、凭据范围、工具调用/墙钟/费用动态计量 |
| 研究契约 | request、evidence、thesis、handoff 的语义边界 | request/evidence/thesis 三个严格实例 Schema 已实现；时间、来源、哈希、缺失、Point-in-Time 和血缘正反例已覆盖 | Typed Handoff 实例、跨 Agent 路由与暂停恢复 |
| 注入与交接 | 不可信文字不得成为工具或 handoff；首版不启用交接 | prompt-like 证据作为数据通过，不能改变绑定或权限；`callable_agents=[]` | handoff 启用后的伪造工具 JSON、越权目标、循环、重复和预算增加拒绝 |
| thesis-tracker | 首个 Skill 的输入输出与 Crypto 边界 | 固定夹具可重放；支持/反对证据、显式失效、修订幂等、来源许可和 Daily/Monitor 全量回归通过 | 真实数据适配、来源质量评估、人工复核与长期校准 |

## 本次 P0 基线复跑（2026-09-22）

基线提交 `12407081cb882ae526180145237f32093f83dffc` 在 Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下运行 `python -m unittest discover -s tests -v`：共运行 81 个测试，其中 79 个通过、0 个失败、2 个跳过。P0 变更后的完整回归共运行 86 个测试，其中 84 个通过、0 个失败、2 个跳过。跳过项都是未配置专用解释器的真实 Qlib 与 bt 测试；历史真实依赖记录没有被冒充成本次复验。固定 tree、环境和夹具哈希见 `docs/P0_BASELINE_REPORT.md`。

## P1 Agent 入口本地回归（2026-09-22）

Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下完整运行 96 个测试：94 个通过、0 个失败、2 个跳过。P1 新增行为测试验证精确目录解析、Agent 与直接 Recipe 的同一运行器/步骤语义、审计身份、目录重复键、清单和 Skill 内容篡改、未知版本/Recipe/绑定、额外能力、非 verified 状态、模型需求、不安全/非 JSON YAML，以及非法审计上下文在创建运行目录前被拒绝。两个跳过项仍是未配置专用解释器的真实 Qlib 与 bt 测试，未被并入通过数。

## P2 观点跟踪本地回归（2026-09-22）

Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下完整运行 106 个测试：104 个通过、0 个失败、2 个跳过。P2 新增 10 个行为测试，覆盖 Golden Fixture 精确哈希、重复运行确定性、证据重复应用幂等、Point-in-Time 截止、内容篡改、标的不一致、未知字段、证据 ID 冲突、伪造旧状态、额外能力、显式失效条件、Agent 精确身份、三角色最小权限、不可信文本隔离和第三方来源/许可证追溯。全量回归同时重跑原有 Daily、Monitor、P0/P1、Qlib 和 bt 协议测试。两个跳过项仍是未配置专用解释器的真实 Qlib 与 bt 集成测试，未被并入通过数。

## P3a 只读结果 API 本地回归（2026-09-22）

Windows 11、CPython 3.12.8、`PYTHONUTF8=1` 下完整运行 113 个测试：111 个通过、0 个失败、2 个跳过。P3a 新增 7 个行为测试，使用真实 P2 夹具生成运行包，覆盖健康端点脱敏、Bearer 认证、摘要 Schema、内部路径/证据隐藏、Markdown 哈希与 ETag、重复刷新无写入、非法运行 ID、跨 subject、失败运行安全摘要、包/报告篡改拒绝和 CLI loopback/token 闸门。两个跳过项仍是未配置专用解释器的真实 Qlib 与 bt 集成测试；OpenStock 和任何任务写接口未参与验证。

## P3c 首条受控提交路径本地回归（2026-09-23）

Windows、`PYTHONUTF8=1` 下完整运行 124 个测试：121 个通过、0 个失败、3 个跳过。行为测试覆盖显式启用与默认只读隔离、严格请求 Schema、Bearer、登记夹具与运行根目录隔离、哈希/请求 ID 校验、同键重试及冲突、并发至多一次执行、运行摘要和报告读取，以及本机监听和 token 启动闸门。新增回归检查拒绝 Windows junction 运行根目录；符号链接用例在本机因缺少创建权限跳过，交由 Linux CI 执行。其余两个跳过项仍是未配置专用解释器的真实 Qlib 与 bt 集成测试；这不验证任务队列、取消、强制墙钟预算、OpenStock 写界面或生产部署。

## P3d 协作取消内核本地回归（2026-09-23）

Windows、`PYTHONUTF8=1` 下完整运行 126 个测试：124 个通过、0 个失败、2 个跳过。新增 4 个行为测试覆盖首步前取消、步骤间取消并保留已完成包、AgentRuntime 透传、无效/异常回调的状态隔离。取消仅在步骤边界检查，当前提交 API 未暴露取消接口；P3a 只读摘要 v1 也不宣称支持 `cancelled` 状态。

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

未覆盖：真实 DeepSeek 外部联调、在线数据源、真实 thesis 数据适配与来源质量判断、Qlib 供应商数据、Qlib 模型训练、真实行情回测语义、模型驱动 Agent、动态工具调用/墙钟/费用限制、人工暂停恢复、Tool Broker、Typed Handoff、OpenStock UI 与任务提交/取消 API、多用户身份/TLS/速率限制、MLflow、Pandera、容器/操作系统级隔离、多来源实盘对账、模型收益评价和实盘交易。
