# QuantAgent Recipe Spec v1

配方是顺序执行的 JSON 文档，包含 `recipe_id`、`recipe_version`、说明和非空 `steps`。

每个步骤必须声明唯一 `id`、`capability`、默认 `plugin` 及对象型 `config`。配置值可以使用完整占位符 `${parameter}`；缺少参数时运行失败，不进行字符串猜测。

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

第二套套餐只支持 Crypto 的 24/72/168 自然小时；缺少 `decision_at` 时必须标记不可评价，不得以 `finalized_at` 代替。

第三套套餐通过 `model.daily_analysis` 能力替换模型步骤。默认回放插件完全离线；DeepSeek 适配器必须显式绑定、开启在线模式并授权网络与环境密钥权限。`model_options` 是插件专属配置对象，允许替换模型时不修改上下游契约。
