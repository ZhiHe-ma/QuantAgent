# QuantAgent P1 Signal Audit SQLite v1

状态：设计冻结候选稿  
基线：P0.2，生产源码 SHA-256 `e0b866ac0ca3bf77868b8b08e5a42ed882dc594c56849853629835948ec8d2fc`

## 1. 本阶段目标

Signal Audit 的职责是把“当时知道什么、做了什么判断、后来发生什么”保存成可回放的结构化证据。v1 只记录已经成功完成的 Daily 信号，不接模拟盘、实盘或本地预测模型。

数据库建议路径：

```text
/home/admin/QuantAgent/10_DailyNotes/signal_audit.sqlite3
```

数据库属于服务器运行状态，不进入 Git；本机通过 `pull_runtime.ps1` 单向拉取快照或备份。

## 2. 数据关系

```text
audit_runs 1 ─── N daily_signals 1 ─── N signal_factors
                              └─────── N signal_outcomes
```

- `audit_runs`：记录一次成功完成或事后修复的 Daily 执行，包括代码版本、模型和交付状态。
- `daily_signals`：记录资产级判断、原始置信度、市场快照、完整模型文本和数据质量。
- `signal_factors`：把进入推理层的新闻因子拆成可查询行，同时保留原始 JSON。
- `signal_outcomes`：保存 T+1、T+3、T+7 的价格和收益回填。
- `schema_migrations`：记录已应用的数据库迁移版本。

## 3. 强制重跑与 canonical 规则

每次真实完成的运行都有独立 `run_id`，因此 `FORCE_DAILY_RUN=true` 不会覆盖历史证据。

同一 `signal_date + asset + decision_horizon` 只允许一条 `is_canonical=1`。成功写入新的强制重跑结果时，应在同一事务内：

1. 把旧 canonical 信号改为 `is_canonical=0`；
2. 插入新信号并设为 `is_canonical=1`；
3. 插入对应因子；
4. 提交事务。

历史行永不物理覆盖或删除。

## 4. 副作用与流水线边界

必须遵守以下约束：

- `DRY_RUN=true`：不得连接或创建 SQLite 文件，只在内存中生成审计预览。
- 幂等跳过：不得新增 run 或 signal；若当天审计缺失，只允许进入明确的 reconciliation 路径。
- 正常生产顺序保持不变：写日报 → 推企业微信 → 生成胶囊 → 保存 Memory → 提交 Signal Audit。
- Signal Audit 写入必须是单个 SQLite 事务。
- Audit 写入失败不得回滚或破坏已经交付的日报与 Memory；应返回失败并记录可重试告警。
- 事后修复使用 `run_kind='reconciled'`，禁止伪装成原始定时运行。

之所以把 Audit 放在 Memory 之后，是为了保持已经验证过的日报交付顺序，并避免审计失败阻止核心内参交付。缺失审计由显式 reconciliation 补齐。

## 5. 时间、数值与 JSON 规范

- `signal_date` 使用服务器业务日期 `YYYY-MM-DD`。
- 时间戳统一保存带时区 ISO-8601；禁止无时区时间进入新记录。
- `confidence_raw` 保留 LLM 原始 0–100 数字，不把它描述成真实概率。
- `confidence_calibrated` 在拥有历史校准模型前保持 `NULL`。
- `reference_price` 是生成信号时的资产价格，不是成交价。
- 收益统一为百分数，例如 `2.5` 表示 `+2.5%`。
- JSON 字段必须使用规范 JSON；SQLite 用 `json_valid()` 约束拒绝损坏数据。

## 6. 数据质量评分 v1

分数范围 0–100，建议从 100 开始扣分：

- 缺少资产参考价格：-35
- 缺少 S&P 500：-10
- 缺少 VIX：-10
- 缺少 Fear & Greed：-5
- 没有入模新闻因子：-10（不是错误，只降低信息完备度）
- 模型或源码版本未知：-10
- reconciliation 重建：-10

所有扣分原因同时写入 `quality_flags_json`，不能只保存总分。

## 7. 收益回填规则

v1 预留三个固定观察窗：

| horizon_hours | 含义 |
|---:|---|
| 24 | T+1 |
| 72 | T+3 |
| 168 | T+7 |

回填必须保存 `entry_price`、`exit_price`、`observed_at`、`price_source` 和数据质量。`direction_correct` 只用于方向判断审计：

- bullish 系列：收益大于 0 才算正确；
- bearish 系列：收益小于 0 才算正确；
- neutral/unknown：保持 `NULL`，后续单独定义中性区间，禁止现在拍脑袋打标签。

## 8. 迁移纪律

- 每个迁移文件只前进，不修改已经进入生产的旧迁移。
- 文件命名：`NNN_description.sql`。
- 应用迁移前备份数据库。
- 每个迁移在一个事务内执行；成功后写入 `schema_migrations`。
- 应用器重复运行必须幂等。
- v1 不自动导入历史 Markdown；历史回填应使用独立命令并标记 `run_kind='reconciled'`。

## 9. 不进入 v1 的内容

- 不训练 Logistic Regression、LightGBM 或 LLM。
- 不把 `confidence_raw` 当作校准概率。
- 不接 ETH、BNB、SOL 实时信号，但 Schema 的 `asset` 字段已预留。
- 不做交易指令、仓位、PnL 或交易所账户表。
- 不做语义去重或 Funding/OI/ETF Flow，这些属于后续数据层升级。

## 10. 下一实现切片

设计确认后，下一 PR 只实现：

1. `signal_audit.py`：连接、迁移、事务写入和查询；
2. 单元测试：空目录不建库、DRY_RUN 零副作用、迁移幂等、强制重跑保留历史、canonical 唯一、坏 JSON 回滚；
3. `agent_engine.py` 最小接线：仅在 Memory 成功保存后调用审计边界；
4. `pull_runtime.ps1` 增加 SQLite 一致性快照拉取，禁止直接复制正在写入的数据库文件。

未来收益回填作为独立 PR，不与首次入账混在一起。
