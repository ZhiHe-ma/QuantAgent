# QuantAgent Recipe Spec v1

配方是顺序执行的 JSON 文档。当前运行器要求 `recipe_id`、`recipe_version`、可选说明和非空 `steps`；P1/P2 的 Agent 入口还会对目录中的 Skill 绑定、入口/出口契约、步骤上限和 `before_run` 自动校验做执行前验证。其余预算与审查字段仍只是冻结语义，不能作为已动态执行的依据。

## 当前结构（已实现）

每个步骤必须声明唯一 `id`、`capability`、默认 `plugin` 及对象型 `config`。配置值可以使用完整占位符 `${parameter}`；缺少参数时运行失败，不进行字符串猜测或局部字符串插值。

运行前检查：

1. 绑定后的插件存在于精选目录且未停用。
2. 插件能力与步骤能力相同。
3. 上一步输出契约属于下一步允许的输入契约。
4. 权限和离线要求全部满足。

能力绑定可以替换同类插件而不改后续步骤。例如 `source.signal_history` 可在 SQLite 与 JSON 适配器间切换。每次运行保存步骤插件版本、输入输出契约、内容哈希、时间、状态和原生数据包。

当前验证套餐：

- `historical-data-health@1.0.0`：SQLite/JSON → 数据体检 → Markdown 报告。
- `offline-outcome-backfill@1.0.0`：已保存信号包重放 → 固定历史价格评价 → 预览或事务回填 → Markdown 报告。
- `offline-daily-research@1.0.0`：日报 JSON 上下文 → 固定分析重放 → 生产兼容 Markdown 日报。
- `qlib-factor-research@1.0.0`：固定 CSV → 隔离 Qlib worker → 因子报告。
- `bt-portfolio-backtest@1.0.0`：固定面板 → 隔离 bt worker → 假设优先的回测报告。
- `thesis-tracker@1.0.0`：严格离线研究夹具 → 确定性观点修订 → 不含原始证据摘录的 Markdown 报告。

结果回填只支持 Crypto 的 24/72/168 自然小时；缺少 `decision_at` 时必须标记不可评价，不得以 `finalized_at` 代替。日报配方默认回放完全离线；DeepSeek 适配器必须显式绑定、开启在线模式并授权网络与环境密钥权限。`model_options` 是插件专属配置对象，允许替换模型时不修改上下游契约。

## Agent/Skill 保留字段

以下字段由规范冻结。P1/P2 Agent 入口只实现精确 Skill/Recipe 绑定、入口/出口契约、`max_steps` 和 `before_run` 自动校验；其他语义尚未由 `RecipeRunner` 动态执行。

| 字段 | 规则 |
| --- | --- |
| `skill_binding` | 精确 `skill_id` 和版本；运行 Agent 必须允许该 Skill，Skill 也必须列出本配方 |
| `input_contract` / `output_contract` | 配方入口和最终输出契约；必须与首末插件实际契约一致 |
| `limits` | `max_steps`、`max_tool_calls`、`max_wall_seconds` 和带币种的最大费用；运行器取所有来源中的最小值 |
| `review_gates` | 稳定 `gate_id`、触发条件、动作和拒绝处理；只能引用允许的自动检查或人工审查类型 |
| `failure_policy` | 默认 `fail_closed`；只有无副作用且插件声明 `retry_safe` 的步骤可配置有限重试 |
| `parent_run_policy` | 规定是否允许父运行引用、最大深度和预算继承；首个单 Agent 版本不创建子运行 |

步骤级可增加 `review_gate`、`timeout_seconds` 和 `max_calls`，但不得高于配方、Agent、部署策略或用户授权的限制。未知控制字段必须拒绝，不得静默忽略。

## Skill 绑定与 Agent 调用

`Agent → Skill → Recipe → Plugin` 是职责关系，不是每次调用都必须经过的链条。命令行仍可直接运行配方；Agent 入口只能选择其 AgentManifest 允许、SkillManifest 兼容且目录中精确版本存在的配方。

Agent 产生的是结构化计划和参数候选。主机必须重新验证：

1. Agent、Skill、Recipe 和 Plugin 的精确身份及版本；
2. 输入数据包引用、契约和访问范围；
3. 能力与有效权限交集；
4. 步骤数、工具调用、时间和费用预算；
5. 审查节点和幂等键；
6. 绑定后完整配方的契约连续性。

自然语言、研究证据和模型文本不能直接生成插件 ID、文件路径、网络目标或权限。未知插件、未知能力、未验证组合或超预算计划必须失败关闭。

P2 的 `thesis-tracker` 固定为 Reader → Analyst → Writer 三步。输入包含旧观点状态与证据包；Analyst 对证据 ID 精确去重，并按支持、反对、背景和显式失效影响派生新状态。相同证据再次作用于已更新状态时返回原状态；证据 ID 内容冲突、未来信息、哈希不符、标的不一致或额外能力请求都失败关闭。所谓“证据充分”仅代表同时存在支持和反对证据且至少有两个不同 `origin_ref`，不代表外部事实、来源质量、投资结论或收益已经验证。

## 运行与恢复

- 第一版继续顺序执行，不预建通用并行/多 Agent 调度器。
- 运行开始前完成可静态判断的校验；拒绝时不创建运行目录。
- 每一步保存精确实现版本、配置摘要、输入/输出包哈希、开始/结束时间、状态和错误。
- 有副作用动作使用幂等键；重复请求返回已有状态或明确冲突，不重复执行。
- `paused_for_review`、`cancelled`、`failed` 和 `completed` 分开记录。恢复必须从已验证检查点开始，不能只依赖模型对上次状态的叙述。
