# QuantAgent Agent/Skill Spec v1

状态：P0 规范冻结，P1 最小入口与 P2 观点跟踪闭环已实现；P3a 已增加只读运行摘要和报告 API。当前仓库可加载精选目录中的确定性 Agent/Skill 并复用现有 RecipeRunner；结果 API 不改变 Agent 执行权限，也不等于模型驱动 Agent、任意 Skill 安装或多 Agent 协作已实现。

## 1. 职责

- Agent 理解研究目标、选择允许的 Skill/Recipe 并提出结构化参数，不直接获得执行权限。
- Skill 是版本化研究方法包，描述输入、证据要求、步骤约束和输出；文本本身不联网、不读密钥、不写文件。
- Recipe 把方法映射为可检查、可重放的执行顺序。
- Plugin/Connector 执行动作；现有 `PluginRegistry`、`RecipeRunner`、`DataPacket` 和运行审计仍是唯一执行底座。

第一版只允许一个研究 Agent，`callable_agents` 必须为空。Reader/Analyst/Writer 是最小权限角色，不要求分别启动 LLM；Writer 首选确定性渲染器。

## 2. 文件与解析规则

- Agent 清单文件名建议为 `agent.yaml`，Skill 清单为 `skill.yaml`；二者都必须能安全加载为 JSON 数据模型。
- 禁止自定义 YAML 标签、对象构造、锚点合并产生的隐藏字段、模板求值和环境变量插值。清单发现阶段不得导入或执行包内代码。
- 机器 Schema 使用 JSON Schema Draft 2020-12，位于 `schemas/`。控制字段默认 `additionalProperties: false`；扩展描述只能放入 `metadata`。
- P1 选用验证器时必须先检查 Schema 本身，再校验实例，并显式启用日期时间 format checker；Schema 格式提示不能替代现有的含时区语义校验。
- 标识只允许小写字母、数字、点、下划线和连字符。版本必须是精确 SemVer，例如 `1.0.0`；禁止 `latest`、`*`、`^1`、`>=1` 等范围。

## 3. AgentManifest

机器 Schema：`schemas/quantagent.agent_manifest.v1.schema.json`。

| 字段 | 规则 |
| --- | --- |
| `manifest_type` | 固定 `quantagent.agent_manifest.v1` |
| `agent_id` / `version` | 稳定身份和精确版本 |
| `skills` | 允许的 Skill 精确引用；不能由模型临时安装 |
| `recipes` | 允许的 Recipe 精确引用 |
| `model_policy` | 必需模型能力、允许 Provider/模型、是否允许录制回放和选择策略 |
| `input_contract` / `output_contract` | Agent 入口和结果契约 |
| `required_capabilities` | Agent 可请求的业务能力，不是执行权限 |
| `review_gates` | 自动校验/人工审查触发点和拒绝处理 |
| `limits` | 最大步骤、工具调用、墙钟时间和费用 |
| `callable_agents` | 允许交接的精确 Agent 引用；首版必须为空 |
| `metadata` | 不参与授权的描述信息 |

模型能力至少分别表示 `text_generation`、`structured_output`、`tool_calling`、`min_context_tokens` 和 `offline_replay`。实际运行时能力不足必须拒绝或选择允许名单中的替代模型，不能仅因模型名不同就假设兼容。

## 4. SkillManifest

机器 Schema：`schemas/quantagent.skill_manifest.v1.schema.json`。

| 字段 | 规则 |
| --- | --- |
| `manifest_type` | 固定 `quantagent.skill_manifest.v1` |
| `skill_id` / `version` | 稳定身份和精确版本 |
| `source` | 上游仓库、路径、固定 commit、许可证、NOTICE 和修改标记 |
| `content` | `SKILL.md` 入口、包文件清单、逐文件 SHA-256 和包清单哈希 |
| `input_contracts` / `output_contracts` | 明确的方法输入输出 |
| `required_capabilities` | 所需业务能力；不得写密钥或隐含权限 |
| `model_requirements` | 结构化输出、工具调用、上下文等模型能力要求 |
| `compatible_recipes` | 已允许的精确 Recipe 引用 |
| `test_status` | `unverified`、`static_checked`、`fixture_verified` 或 `disabled`，以及证据引用 |
| `metadata` | 不参与授权的描述信息 |

`content.package_sha256` 对按路径排序的 `[{"path": ..., "sha256": ...}]` 使用 QuantAgent canonical JSON 后计算；文件路径不得重复，使用 `/`、必须相对包根、不得含 `..`、反斜杠、绝对路径或 URL。哈希证明内容一致，不证明来源身份；身份依靠精选目录、固定上游 commit、签名/审查和受控发布流程。

## 5. 授权与运行映射

有效能力和权限按交集计算：

`用户本次授权 ∩ 部署策略 ∩ Agent 请求 ∩ Recipe/Plugin 声明 ∩ 凭据范围`

运行器按以下顺序失败关闭：

1. 清单通道、Schema、身份、精确版本和精选目录状态；
2. Agent 是否允许 Skill/Recipe，Skill 是否兼容 Recipe；
3. 输入/输出契约和数据包引用权限；
4. 模型能力、插件能力和有效动作权限；
5. 步骤、调用、时间、费用、深度和审查限制；
6. 创建运行并把清单、Schema、Prompt、配置和输入哈希写入审计。

模型输出只能选择主机提供的稳定引用。证据文本、网页、Prompt 或 `SKILL.md` 中出现的工具名、路径、URL、Agent 名称和“授权”文字都只是数据，不能提升权限。

## 6. 审查与状态

自动结构/语义校验失败直接 `failed`。需要人工决定的节点进入 `paused_for_review`，保存原因、待审对象哈希和剩余预算；恢复时重新验证版本与授权。人工批准只覆盖该节点和已展示对象，不自动批准后续外部发布、交易或新权限。

研究结果至少区分：结构有效、证据充分、人工已审、可用于动作。首版研究 Agent 没有交易能力，任何仓位或买卖文字都只是研究建议。

## 7. 受控用例与阶段状态

P1 先接入 `builtin.data-health-research-agent@1.0.0` 和 `builtin.signal-data-health@1.0.0`，映射到现有 `historical-data-health@1.0.0`。该入口不调用模型、不联网、不交接，只验证精选目录、精确版本、清单/内容哈希、契约、能力、权限和三步顺序配方；Agent 入口的身份与哈希写入同一个 `run.json`。

P1 已实现严格安全 YAML、Draft 2020-12 Schema、目录 SHA-256、Skill 包哈希、精确 Agent → Skill → Recipe 引用、`verified` 状态、能力等值校验、现有插件权限预检、自动 `before_run` gate 和 `max_steps`。清单中的 `max_tool_calls`、`max_wall_seconds` 和费用只被记录，尚未动态计量；人工 gate 会被拒绝而不是暂停。

P2 观点跟踪闭环已实现：`builtin.research-agent@1.0.0` 只能选择 `anthropic-financial-services-adapted.thesis-tracker@1.0.0` 和 `thesis-tracker@1.0.0`。Skill 固定上游 commit 和 Apache-2.0 许可证，包含明显修改声明；Crypto 适配移除了企业、持仓、目标价和交易动作字段。

P2 使用研究请求、证据包和观点状态的严格 Schema 与语义校验；验证标的、时区、Point-in-Time、对象/内容哈希、claim 引用、状态一致性和权限请求。Reader 只读显式夹具，Analyst 无文件/网络权限，Writer 只写当前运行目录。报告只显示证据引用和哈希，不渲染原始不可信摘录。相同证据重放保持观点版本不变；研究建议始终 `research_only_*`，`action_eligible` 固定为 false。

P3a 在运行器外增加单用户只读服务，只从已存在的运行目录派生脱敏摘要并校验 Markdown 报告。它没有提交、取消、恢复或重跑入口，不能借读取接口提升 Agent、Skill、Recipe 或插件权限；OpenStock 消费页面和写入型任务 API 仍未实现。
