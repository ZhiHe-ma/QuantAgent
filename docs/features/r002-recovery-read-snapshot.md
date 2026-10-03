# R002：恢复状态读取的一致性

```json
{
  "branch": "feature/r002-recovery-read-snapshot",
  "base_commit": "f61191cb3398e516f9beb01545f61ce5a06c4af9",
  "phase": "verified",
  "components": ["recovery-storage", "acceptance-tests", "architecture"],
  "readme_unchanged": {
    "architecture": "本批仅新增遵循既有格式的分支验收记录，门禁命令、文档格式及预算规则未改变，tools/architecture/README.md 无需更新。"
  }
}
```

## 目标与非目标

修复 [R001 遗留](r001-recovery-resume.md#遗留问题)：一次正常并发提交可能使 status 把旧状态行与新事件误判为损坏。用户已同意先复现、修复同一读取快照并完成回归。沿用隔离工作树，在新分支执行；原用户文件删除保留。

范围是 get、find_daily、list_open 的内部读取一致性。公开接口、数据库版本、事件规则、写入授权和恢复流程保持；不实现学习业务，也不上传、合并或部署。

## 涉及模块

[恢复存储](../../quantagent_platform/recovery/README.md)与[契约测试](../../tests/contract/README.md)。同步恢复 README、测试导航与本记录；保留 R001 当时的结论。

## 接口或数据变化

根因：连接使用 isolation_level=None，但只在写入时开启事务；状态行、事件及列表中的各条任务可能读取不同版本。读取连接将使用短只读事务，把 schema 校验、任务选择和事件重建置于同一快照；写入仍使用 BEGIN IMMEDIATE。

以真实临时 SQLite／独立连接精确交错提交，覆盖正常查询、列表整体一致性及实际损坏拒绝。WAL 仅用于测试允许提交在读取中完成，不改变产品 journal_mode；依据见 [SQLite 官方隔离说明](https://www.sqlite.org/isolation.html)。原默认模式另核对读取结束或出错后仍可写入。

## 新增依赖

无新增依赖、能力、允许引用或豁免；修改既有登记源码和测试，调度钩子仅放测试中。

## 测试证据

2026-10-03，Windows／Python 3.12.8／UTF-8。目标基线 f61191c：`python -m unittest tests.contract.test_recovery_store tests.contract.test_recovery_ports tests.unit.test_recovery_rules tests.architecture.test_recovery_boundaries -v`，15 项通过，0.205 秒；日志在忽略的 artifacts/architecture/r002-read-snapshot/baseline.log。

初始阅读清单 `python -m tools.architecture --context-for recovery-storage --context-for acceptance-tests`：5 份、210 行／10,931 字符，PASS。

`python -m unittest tests.contract.test_recovery_store.RecoveryStoreTests.test_status_reads_use_one_snapshot_during_valid_event_commit tests.contract.test_recovery_store.RecoveryStoreTests.test_list_open_does_not_mix_snapshots_between_records -v`：修复前 2 项、6 个子场景失败，1.025 秒。get、find_daily、list_open、筛选列表和 dry-run 查询均复现 journal projection mismatch；列表复现同一结果中的 revision 0／1 混读。所有 SQL 和提交实际执行，连接工厂只安排交错位置，未伪造查询结果。

最小修复是在只读分支开启 BEGIN，覆盖 schema／任务选择／事件重建；既有 finally 负责 rollback／关闭。原定向命令修复后 **17 项通过，0.463 秒**；同时核对新提交可见、实际损坏拒绝与默认模式错误后写入成功。日志为 red.log／green.log。

受验收源码 `36b4ac471edccc668f325ce764e835b9efbc1c51`：`python -m unittest discover -s tests -v` **395 项、0 失败、7 项原环境跳过，148.121 秒**，退出 0；日志为 full-tests.log。跳过为真实 bt／Qlib 解释器未指定、私人固定 P4 样本缺失、三项 Windows 链接权限用例和 8.3 短路径不可用，不记作通过。

`python -m tools.architecture --base-ref f61191cb3398e516f9beb01545f61ce5a06c4af9 --branch feature/r002-recovery-read-snapshot --report artifacts/architecture/r002-read-snapshot/gate.json`：PASS，68 个模块、0 条登记存量违规、Import Linter 返回 0。完整涉及范围的阅读清单（另加 `--context-for architecture`）：6 份、262 行／13,420 字符，PASS，见 context-final.json。

新上下文只读审查核对 `f61191c..36b4ac4` 的源码、测试、说明及原始日志，无 Critical／Important／Minor；认为本批修复可交付。审查接受的范围排除：跨主机和物理灾难沿用既有拓扑，本批未验证；真实服务、远端 CI、部署和生产不能由本地日志证明；原用户文件删除保持且未暂存。没有重复运行全仓测试来充当独立审查证据。后续提交仅补本记录，验收源码不变；完整版本与日志摘要保存在本地 receipt.json。

## 回滚方式

回退本批源码、测试和当前说明；没有 schema 迁移或业务数据修正。保留本地证据，原恢复日志及用户删除不纳入回退。

## 遗留问题

默认 rollback journal 的短读取事务可能短暂阻塞写入提交，沿用现有超时；不把 WAL 测试记作产品模式变更。真实服务、跨主机、远端 Windows／Linux CI、部署与生产不属于本轮本地验证。
