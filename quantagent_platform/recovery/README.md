# 本地执行恢复

## 职责与边界

保存同一授权实例的冻结研究快照和追加事件，使 Daily／Monitor 中断后继续原任务。工作流判断执行顺序，数据所属方负责文件、消息和审计；恢复存储只保存运行记录。

## 文件导航

先读 [contracts.py](contracts.py) 的类型／存储接口，再读 [rules.py](rules.py) 的校验和转换。[sqlite_store.py](sqlite_store.py) 实现 SQLite 与锁，空包入口没有公开导出。流程在 [Daily](../legacy_daily_recovery.py)、[Monitor](../legacy_monitor_recovery.py) 和 [人工动作](../legacy_recovery_actions.py)，历史与验收见 [R001](../../docs/features/r001-recovery-resume.md)。

## 对外接口

`freeze_snapshot` 冻结正文，`transition` 纯函数生成状态。`SQLiteRecoveryStore(daily_dir, dry_run=False)` 提供 get、find_daily、list_open、create、append_event 和 lock；构造不创建文件，缺库查询为空。事件按 expected_revision 防止覆盖，同编号同内容提交幂等。

get、find_daily、list_open 在同一短只读事务中校验 schema、选择任务并重建事件；并发提交不会让一次返回混入不同版本。查询返回该快照的状态，后续查询可见新提交；实际版本、实例或日志损坏仍拒绝。

非法协议、哈希、实例或转换拒绝；修订冲突抛 RecoveryConflict，已占用锁抛 RecoveryBusy。Daily 未完成只补缺失步骤；消息 running 中断变 unknown，人工确认未收到后须明确 retry。无渠道快照只允许显式 retry 追加首次绑定，提前落盘失败不能绕过。首次审计载荷独立冻结，后续确认不改旧标记。Monitor 保留原新闻、日期、推理决议和次数，所需投影确认后才完成；同批 ID 按已确认投影去重，存储失败不消耗推理预算。读取遇到短投影锁竞争时每秒退让重试；同类执行锁仍拒绝并发运行。

## 依赖规则

契约只依赖标准库；规则只依赖契约，适配器使用公开契约与校验。只有 bootstrap 注入 SQLite 实现；工作流只引用公开 ports 与纯规则。精确归属见 [能力清单](../../docs/architecture/components.json)。

## 数据与权限

实例标识是规范化绝对 daily_dir 的哈希。该目录拥有 quantagent_recovery.sqlite3 和锁文件，记录公共研究与运行事实，不保存密钥或私人决定。Daily／Monitor 执行锁独立；短 projection 锁协调文件，SQLite 事务不跨网络、模型、文件或其他数据库。dry-run 禁止写入和锁操作。

## 测试与验收

运行 `python -m unittest tests.unit.test_recovery_rules tests.contract.test_recovery_store tests.contract.test_recovery_ports tests.integration.test_daily_recovery tests.integration.test_monitor_recovery tests.integration.test_recovery_processes tests.architecture.test_recovery_boundaries -v`。测试使用合成外部服务、真实临时文件／SQLite／OS 锁，并以 os._exit 中断真实子进程；实际命令、环境、提交与结果见 R001。[R002](../../docs/features/r002-recovery-read-snapshot.md)补充真实独立连接的确定性交错、列表快照、损坏拒绝与默认模式错误后锁释放验收。命令用法见 [使用说明](../../docs/USAGE.md#本地恢复)。

## 已知限制

仅单机同目录实例，不支持复制库后自动接管、跨主机或物理灾难恢复。unknown、人为改动和资料不足的旧半成品须人工处理；没有整体原子交付或消息恰好一次保证。默认 rollback journal 的读取事务可能短暂延迟写入提交，沿用现有超时，查询结束或异常时释放；产品不自动切换 WAL。完成记录保留，清理政策另批制定。真实服务、Linux CI 与生产验收分别记录。
