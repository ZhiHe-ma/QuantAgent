# QuantAgent Data Contract v1

平台步骤只交换带版本和哈希的数据包，不直接共享任意 Python 对象。本文件同时区分当前运行器已经执行的规则与后续 Agent/Skill 阶段预留的契约；预留契约不等于已有实现。

## 通用包络（已实现）

| 字段 | 规则 |
| --- | --- |
| `contract_version` | 完整契约名，例如 `quantagent.signal_history.v1` |
| `packet_type` | 数据类别，不代替契约版本 |
| `source` | 产生数据的插件 ID |
| `created_at` | 必须含时区的 ISO 8601 时间 |
| `records` | JSON 对象数组；原始业务记录不被强制压成单一总表 |
| `metadata` | 来源、版本、限制、转换和血缘说明 |
| `content_sha256` | 只对规范化后的 `records` 计算 SHA-256 |

规范化使用 UTF-8 JSON、键排序、无额外空白且禁止 NaN/Infinity。当前 `content_sha256` 不覆盖 `metadata`、`source`、`created_at` 或来源身份；不得把它描述为完整包签名。若后续需要完整包哈希或签名，必须新增独立字段或新契约版本，不能静默改变 v1 含义。

空值使用 JSON `null`，并在具体契约中提供缺失原因；不以零、空字符串、默认日期或当前日期代替未知。收益、币种、市场、复权、事件时间与可用时间必须由具体契约另行声明。

## 版本与兼容

- 契约名最后一段是主版本。删除必填字段、改变单位/时间语义、扩大控制消息可执行含义或改变哈希范围，必须升级主版本。
- 同一主版本只能增加真正可选且有明确默认解释的描述性字段。控制消息默认拒绝未知字段，不能靠“宽松解析”获得前向兼容。
- 生产者必须写精确契约版本；消费者只接受显式允许名单中的版本，不使用通配符或“最新”。
- 每次转换保留父包引用、输入哈希、转换规则版本和信息损失说明。不能恢复的信息标记为缺失，不得猜测。

## 现有契约（已实现）

- `quantagent.signal_history.v1`：历史判断记录。体检所需字段为 `signal_id`、`signal_date`、`asset`、`quote_asset`、`bias`、`finalized_at`。
- `quantagent.data_quality.v1`：字段缺失、重复标识、时间合法性及未评价项。
- `quantagent.signal_outcomes.v1`：按明确决策时间、期限和历史价格生成的评价记录；交换字段 `return_decimal` 使用小数。
- `quantagent.daily_context.v1`：单日日报所需的日期、市场指标、记忆胶囊和新闻因子。
- `quantagent.daily_analysis.v1`：模型分析文本、模型身份、提示词哈希和完整输入上下文。
- `quantagent.report.v1`：报告产物引用，不嵌入或伪造外部评价结果。

现有 SQLite `signal_outcomes.return_pct` 已由旧结构确定为百分数值。写入插件必须把 `return_decimal` 显式乘以 100，并把交换记录完整保存在 `raw_json`；不得仅凭字段名猜测单位。

## 研究语义（P1/P2 契约约束）

新增研究记录至少明确以下语义：

| 类别 | 最低要求 |
| --- | --- |
| 标的 | `asset_type`、规范标识、交易场所、基础/报价币种；`BTC/USD` 与 `BTC/USDT` 不等同 |
| 时间 | 区分事件、发布、采集、当时可用、决策时间；精确时间必须含时区 |
| 数值 | 单位、币种、收益小数/百分数/基点、频率、复权及价格语义 |
| 证据 | 来源引用、采集时间、内容哈希、许可/访问范围、支持或反对的观点引用 |
| 血缘 | 父运行、父包、转换规则、原生结果引用和信息损失 |
| 模型 | Provider、实际模型标识、Prompt/Skill 版本、参数、调用时间和成本 |
| 缺失 | `null` 加机器可读的缺失原因，不补造历史事实 |
| 状态 | 结构有效、证据充分、人工已审、可用于动作分别表示，不合并成单个“可信”布尔值 |

证据正文和第三方材料始终视为不可信数据。即使通过结构校验，也不能直接成为路径、SQL、Shell 参数、网络目标、插件 ID、Agent 目标或权限声明。

## P2 已实现的研究契约

### `quantagent.research_request.v1`

每条记录至少包含：

- `request_id`、`requested_at`、`subject`、`objective`；
- `as_of`，表示本次研究允许使用信息的最晚时间；
- 精确 `agent_ref`、`skill_ref` 和 `recipe_ref`；
- `input_refs`，只引用已授权的数据包 ID/哈希，不接收任意本地路径或 URL；
- `requested_capabilities`、预算与人工审查要求；
- `idempotency_key`，用于拒绝重复的有副作用请求。

### `quantagent.evidence_bundle.v1`

每条证据至少包含 `evidence_id`、`subject_ref`、`claim_refs`、`stance`（支持/反对/背景）、来源、事件/发布/采集/可用时间、内容哈希、摘录或结构化事实、授权范围和缺失项。转载同一原始消息必须通过 `origin_ref` 关联，不能当成独立来源。

### `quantagent.thesis_state.v1`

每条观点状态至少包含 `thesis_id`、标的、版本、`as_of`、核心观点、支持与反对证据引用、失效条件、观察项、上一个版本引用和修订原因。研究建议与实际交易动作分离；该契约不携带下单授权。

P2 还使用 `quantagent.thesis_review_input.v1` 数据包封装同一次离线运行的 request、previous thesis 和 evidence bundle。源文件固定为 `quantagent.thesis_review_fixture.v1`；三个嵌套对象分别校验，引用哈希必须与对象 canonical JSON 一致。证据内容哈希覆盖 `excerpt` 与 `structured_facts`，观点状态只保留证据索引和哈希，并明确记录这一信息损失。

P2 的充分性规则是可审计的最低门槛：至少一个支持证据、一个反对证据和两个不同 `origin_ref`。它只表示夹具具备双向证据结构，不代表来源真实、相互独立或结论正确。`human_reviewed` 与 `action_eligible` 不从该规则推导。

## 预留研究契约

### `quantagent.handoff_request.v1`（P5 才实现执行）

每条交接至少包含 `handoff_id`、根/父运行、来源/目标 Agent 的精确版本、`task_type`、目标输入契约、结构化参数、授权数据包引用、请求/截止时间、深度、剩余预算和幂等键。主机计算有效权限；模型文本不能声明“已获授权”。

控制类契约采用严格字段集合。未知字段、版本通配、未授权引用、无时区时间、过期请求、循环/超深交接或预算增加必须失败关闭。

## 校验顺序

1. 验证 JSON 类型、必填字段、未知字段策略和精确版本。
2. 显式校验日期时间格式与时区；仅在 Schema 中写 `format: date-time` 不足以证明已执行格式校验。
3. 校验业务语义：单位、市场、标的、Point-in-Time 和状态组合。
4. 校验引用对象、哈希、调用主体和访问范围。
5. 记录验证器版本、失败路径和原因；不得把失败数据静默降级为“部分成功”。
