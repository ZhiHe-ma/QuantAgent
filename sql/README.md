# 信号审计持久化

## 职责与边界

保存 signal_audit 的 SQLite 建表迁移；审计运行、规范信号、因素及历史结果由 SignalAuditStore 管理。该审计记录不替代 OpenStock 的用户决定、理由和私有回证。

## 文件导航

- `signal-audit`：[signal_audit](../signal_audit.py)。
- `signal-audit-contracts`：[signal_audit_contracts.py](../signal_audit_contracts.py)：不触发插件包初始化的独立基础异常。
- [001_signal_audit.sql](001_signal_audit.sql)：事务、外键、唯一键和值域约束。

## 对外接口

SignalAuditStore.initialize 创建/迁移指定数据库；record_completed_signal 验证记录并事务写入；get_canonical_signal 读取日期、资产和周期对应的规范信号。值域、必填内容或冲突由 SignalAuditValidationError/SignalAuditError 报错；初始化和写入会修改数据库，读取不应绕过所属模块。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则和当前状态见 [架构规范](../docs/ARCHITECTURE.md)。基础错误由包外纯 `signal-audit-contracts`拥有，本模块及 legacy ports 保留同一类型别名；独立存储导入仅需标准库，不初始化插件主机。实际 SQLite、验证及质检规则仍归本模块，工作流通过启动绑定消费。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

SignalAuditStore.validate_completed_signal 只校验、不打开库；record_recovered_signal 接收冻结的原 run_id／signal_id 与 expected_canonical_signal_id，短事务中仅在前像一致时提升规范信号，较旧补账不能替换新规范信号。同编号提交返回 exists、不增加记录。原 record_completed_signal 和迁移文件保持原接口／强制替换语义。独立审计仍只使用标准库与所属错误契约。

## 已知限制

门禁不是业务语义正确、跨账户隔离或生产可用性的证明。默认路径、迁移及写入规则未改变；错误类型归属迁移，不承诺跨版本 pickle。不得将离线样本结果称为真实收益或自动交易能力。
