# 本地执行恢复

## 职责与边界

保存同一授权实例的不可改写研究快照和追加事件，判断哪些步骤可继续。当前提供契约、纯规则、SQLite 记录和单机锁，Daily／Monitor 均已接入。

## 文件导航

先读 [contracts.py](contracts.py) 的公开类型和存储接口，再读 [rules.py](rules.py) 的快照校验与状态转换。[sqlite_store.py](sqlite_store.py) 实现存储和锁；包入口不统一导出实现。实施与验收历史见 [R001](../../docs/features/r001-recovery-resume.md)。

## 对外接口

`freeze_snapshot` 校验并冻结正文；`transition` 纯函数生成新状态。`SQLiteRecoveryStore(daily_dir, dry_run=False)` 提供 get、find_daily、list_open、create、append_event 和 lock；构造不创建文件，缺库查询返回空。事件使用 expected_revision 防止覆盖并发更新，同编号同内容重复提交幂等。非法协议、内容或转换拒绝；修订冲突抛 RecoveryConflict，被占用锁抛 RecoveryBusy。

## 依赖规则

契约只依赖标准库类型；纯规则只依赖契约。存储适配器依赖公开契约与校验规则，只有启动组装可注入实现；工作流不导入 SQLite 实现。精确登记见 [能力清单](../../docs/architecture/components.json)。

## 数据与权限

实例标识是规范化绝对 daily_dir 的哈希。该目录拥有 quantagent_recovery.sqlite3 和作用域锁文件；记录只保存公共研究及运行事实，不保存密钥或私人决定。Daily/Monitor 执行锁独立，projection 锁用于短文件投影；SQLite 事务只处理记录，不跨网络或其他数据库。dry-run 拒绝写入和锁操作。

## 测试与验收

`python -m unittest tests.unit.test_recovery_rules tests.contract.test_recovery_store tests.architecture.test_recovery_boundaries -v` 验证快照、转换、修订幂等、真实临时 SQLite、实例隔离及 OS 锁；实际命令、环境、提交与结果见 R001。进程中断及工作流验收在对应批次完成后记录。

原数据所属方提供受控报告／Memory 投影、结构化消息结果及审计补账，调用方通过 legacy_ports 使用；本目录的存储不直接修改这些投影或审计库。真实接口与失败场景见 [test_recovery_ports.py](../../tests/contract/test_recovery_ports.py)。

Daily 已接入：步骤执行前记 running，执行后追加结果；本地中断核对目标，消息中断转 unknown。首次审计载荷独立冻结，后续确认不修改原审计标记；确认未收到只改变状态，之后必须有明确 retry 请求。recover 用法见 [使用说明](../../docs/USAGE.md)。

Monitor 已接入原新闻观察、模型结果及预算事件；完成以所需投影全部确认计。跨午夜及源移除仍恢复原 target_date；缓冲成功／去重失败不重复因子。模型重试成功时隔离投影重新待确认，不能沿用上一次失败记录的写入确认。

## 已知限制

仅单机同目录实例；不支持复制库后自动接管、物理磁盘灾难或跨主机锁。未知消息不能自动重发，旧历史不能凭新数据补造快照；没有整体原子交付或消息恰好一次保证。
