# Compatibility Test Matrix

| 层级 | 组合 | 当前证据 |
| --- | --- | --- |
| 单插件 | JSON source 1.0.0 | UTF-8 读取、对象/数组归一、目录限制、大小限制 |
| 单插件 | SQLite source 1.0.0 | `mode=ro`、表存在检查、JSON 列解码、数量上限 |
| 单插件 | Signal quality 1.0.0 | 缺失、重复 ID、无效或无时区时间、空数据 |
| 单插件 | Markdown report 1.0.0 | 仅写运行目录，显示范围和未评价项 |
| 连接处 | source → quality | `quantagent.signal_history.v1` |
| 连接处 | quality → report | `quantagent.data_quality.v1` |
| 整套配方 | JSON → quality → report | 固定样本离线通过 |
| 整套配方 | SQLite → quality → report | 临时数据库离线通过 |
| 安全边界 | 路径越界、权限不足、未知插件 | 失败关闭并记录或在执行前拒绝 |

未覆盖：在线数据源、Qlib、MLflow、Pandera、回测引擎、容器隔离、多来源实盘对账、模型收益评价和实盘交易。
