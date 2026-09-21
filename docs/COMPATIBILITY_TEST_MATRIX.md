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
| 连接处 | source → quality | `quantagent.signal_history.v1` |
| 连接处 | quality → report | `quantagent.data_quality.v1` |
| 整套配方 | JSON → quality → report | 固定样本离线通过 |
| 整套配方 | SQLite → quality → report | 临时数据库离线通过 |
| 整套配方 | packet replay → outcome → SQLite preview/apply → report | 固定价格样本离线通过 |
| 整套配方 | daily JSON → replay analysis → Markdown report | 固定上下文与分析样本离线通过 |
| 安全边界 | 路径越界、权限不足、未知插件 | 失败关闭并记录或在执行前拒绝 |

CI 在 `ubuntu-latest` 和 `windows-latest` 的 Python 3.12 上运行完整离线 unittest；真实外部接口仍须单独报告。

未覆盖：真实 DeepSeek 外部联调、在线数据源、Qlib、MLflow、Pandera、回测引擎、容器隔离、多来源实盘对账、模型收益评价和实盘交易。
