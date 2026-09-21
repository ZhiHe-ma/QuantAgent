# QuantAgent Data Contract v1

平台步骤只交换带版本和哈希的数据包，不直接共享任意 Python 对象。

## 通用包络

| 字段 | 规则 |
| --- | --- |
| `contract_version` | 完整契约名，例如 `quantagent.signal_history.v1` |
| `packet_type` | 数据类别，不代替契约版本 |
| `source` | 产生数据的插件 ID |
| `created_at` | 必须含时区的 ISO 8601 时间 |
| `records` | JSON 对象数组；原始业务记录不被强制压成单一总表 |
| `metadata` | 来源、版本、限制和转换说明 |
| `content_sha256` | 对规范化 `records` 计算的 SHA-256 |

空值使用 JSON `null`，不以零代替未知。收益、币种、市场、复权、事件时间与可用时间必须由具体契约另行声明。

## 首批契约

- `quantagent.signal_history.v1`：历史判断记录。体检所需字段为 `signal_id`、`signal_date`、`asset`、`quote_asset`、`bias`、`finalized_at`。
- `quantagent.data_quality.v1`：字段缺失、重复标识、时间合法性及未评价项。
- `quantagent.report.v1`：报告产物引用，不嵌入或伪造外部评价结果。

插件必须保留原生输入包；转换后的包记录输入哈希。无法恢复的信息必须显式标记，不得猜测。
