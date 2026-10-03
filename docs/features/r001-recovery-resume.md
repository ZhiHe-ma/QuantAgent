# R001 失败恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 失败后复用原研究，只补未完成步骤；消息结果未知时先取得人工确认。

**Architecture:** 纯契约和规则定义恢复状态；独立 SQLite 适配器保存不可改写的快照及追加事件。工作流通过所属 ports 执行文件、消息和审计操作，具体恢复存储仅由 bootstrap 注入。

**Tech Stack:** Python 3.12、标准库 SQLite／文件锁／unittest，现有运行依赖与 Import Linter。

**Spec:** 本文“目标与非目标”至“新增依赖”的书面规范，已批准版本为提交 `2a29b69ef0fd88805f571339603530c69ed4b3ec`。

2026-10-03。书面规范已获用户确认；实施计划已获用户确认，现按五批实施。沿用当前工作树和 Native 执行方式。本文件保存本批规范、计划及验收，共同规则使用链接。

## Global Constraints

- 仅使用已安装运行依赖和 Python 标准库 SQLite/文件锁能力。
- 范围是单机、同一授权实例的进程恢复，不承诺文件与外部消息整体原子提交或消息恰好发送一次。
- unknown 不自动重发。原任务无渠道时，首次显式 retry 可绑定当前渠道并追加事件。
- 原 JSON 文件继续作为兼容投影；不推送、合并或部署。依赖、权限及文档归属引用下面的共同规范。

## Review Focus

1. 中文、换行及 Windows 文件字节：恢复不能误判为人工改动；Task 2 `test_unicode_projection_hash_matches_written_bytes`。
2. 缺配置、缺目录的 status 与 dry-run 操作：不得创建目录、库或事件；Task 3 `test_status_without_configuration_and_dry_actions_are_read_only`。
3. 无渠道任务后来配置消息，或既有渠道发生变化：仅显式补送可首次绑定，改投必须拒绝；Task 3 `test_first_channel_binding_and_channel_change`。
4. 进程跨午夜退出且源新闻消失：仍写原日期，不重做已冻结推理；Task 4 `test_pending_news_survives_midnight_and_source_removal`。
5. 库协议过新、快照哈希不符或实例不匹配：拒绝继续，保留有效数据；Task 1 `test_invalid_version_hash_and_instance_are_rejected`。

---

```json
{
  "branch": "feature/r001-recovery-resume",
  "base_commit": "9c09e12e6bf82c0e1fe3845ee1bf71cd1941a6ea",
  "phase": "implementing",
  "approved_plan_commit": "f38ede46eef828d9eec7ba32798139f09e00fe04",
  "written_spec_commit": "2a29b69ef0fd88805f571339603530c69ed4b3ec",
  "execution_method": "native",
  "components": ["legacy-engine", "legacy-workflows", "legacy-ports", "legacy-composition", "compatibility-exports", "signal-audit", "architecture", "acceptance-tests", "recovery-contracts", "recovery-domain", "recovery-storage", "recovery-package"],
  "readme_unchanged": {
    "architecture": "仅登记实际新增能力及已批准的最小依赖边；扫描、文档检查规则和 CI 使用方式未改，工具 README 现有说明仍有效。"
  }
}
```

## 目标与非目标

使新协议产生的 Monitor/Daily 任务在普通写入异常或进程中断后能继续处理，补回未完成的落盘、Memory 和审计；已冻结的研究结果直接复用，消息结果未知时须人工确认。

成功标准：失败不被误标为完成；完成步骤不会重复执行；重启可读取原快照；审计不重复建信号；历史恢复不覆盖较新状态。范围是单机、同一授权实例的进程恢复，不承诺文件与外部消息整体原子提交或消息恰好发送一次。

采用标准库 SQLite 本地执行记录，不增加外部任务服务。暂不做 OpenStock 联调、历史回证、学习、交易、跨主机恢复、磁盘损毁恢复或运行中热切换；不推送、合并或部署。依赖和数据归属遵守[架构规范](../ARCHITECTURE.md)，文档分工遵守[维护规则](../DEVELOPMENT_TESTING.md)。

## 涉及模块

现有入口、工作流与 ports 见[引擎导航](../architecture/legacy-engine/README.md)；原审计数据由[信号审计](../../sql/README.md)管理。

| 责任 | 本批设计 |
| --- | --- |
| 恢复契约与规则 | 新能力保存快照、状态、错误及存储接口；纯规则负责校验、状态转换和恢复判定，不导入具体 IO |
| 恢复适配器 | 独立 SQLite 库及实例锁；持久化执行记录和追加事件，不直接改写信号审计或私人数据 |
| 原工作流 | 经公开 ports 调度日报、消息、Memory、审计及新闻投影；不访问其他模块私有成员 |
| 启动组装 | 注入恢复存储及各数据所属方的公开操作；原构造入口、默认配方、HTTP 和审计类型别名保持 |

实施时登记真实新增能力及最小公开入口，再同步所属 README。本文不预建空目录，不提前把候选能力当作已存在代码，也不扩大原能力间的允许引用来消除问题。

## 接口或数据变化

### 执行记录与状态

默认恢复库为实例 `daily_dir/quantagent_recovery.sqlite3`，与原信号审计库分开。构造和启动绑定不建库；首次正式任务按授权目录创建。恢复记录不保存 API key、Webhook URL、Cookie 或 OpenStock 私人决定。

Daily 快照在首次交付前完成校验和持久化，保存协议版本、实例标识、固定 run_id/signal_id、日期及带时区时间、报告和消息正文、胶囊、原行情/因子/分析/上一日记忆、目标 Memory 完整投影、预期旧文件哈希、审计研究事实和内容哈希。快照冻结后不修改；交付结果在执行后追加，不能预先写成成功。每次尝试、结果和人工确认追加事件，步骤状态由事件及当前记录共同查询。

本地步骤采用 pending → running → succeeded/failed；冲突进入 needs_review。外部消息另外允许 unknown。任务只有必要本地步骤已解决、消息成功或被明确标记不适用时才完成；failed/unknown/needs_review 不能被“当天已有文件”闸门当作完成。Memory 的 superseded 属于已解决但未更新，完成状态须保留该区别。初次无消息渠道时记 not_configured，视为当前通知不适用；本地完成后正常跳过，配置渠道后仅显式 retry 可以申请第一次发送。

状态变更使用短 SQLite 事务，网络、模型、文件和信号审计操作放在事务之外。恢复适配器分别控制 Daily 和 Monitor 的跨进程执行锁，并以短文件投影锁协调共用文件；模型和网络请求不持有文件投影锁。进程退出后锁可释放；恢复先核对实际结果，再执行可重试步骤，不把超时或锁过期等同于“没执行过”。

### Daily 恢复规则

1. 生成并校验分析、胶囊、审计研究事实和编号后，先冻结快照，再按原交付顺序处理日报、消息、Memory、审计。快照提交失败时不得开始这些交付；无效胶囊不再造成“已发消息但记忆生成失败”。
2. 同日再次启动先查本实例执行记录。未完成任务复用其快照，只补缺失步骤，不重新抓行情、请求模型或生成审计编号；全部完成的任务继续按原幂等返回跳过。
3. 日报和 JSON 使用原子替换；恢复核对冻结内容及预期旧版本。内容已一致则认定该步骤已完成；出现不符合预期的人工改动、目标冲突或损坏时停止该步骤并提示，不能盲目覆盖。
4. Memory 恢复由所属写入接口执行，同日重复不增加滚动日期，较早任务不能覆盖较新胶囊。被新日期取代的写入追加 superseded 事件，不伪报 memory_saved=true；信号审计仍可保存原研究及实际交付状态。
5. 首次审计尝试前，由所属接口根据冻结研究和当时已确认的交付结果生成完整载荷，单独冻结为审计事件，不改原研究快照。之后原审计接口只重试这一载荷及编号；提交后、恢复状态落盘前崩溃时应返回已存在，行数不增加。wecom_sent 表示首次审计载荷冻结时是否确认成功；后续补送或确认追加恢复事件，不重写原研究和当时记录。
6. FORCE_DAILY_RUN 对已完成任务生成新编号及新快照；同日未完成任务先恢复或明确人工终止，不能用强制运行绕过未完成状态、抹掉旧快照或使较旧补账取代新规范信号。

### 消息确认

原生发送接口区分 confirmed、failed、unknown、not_configured；明确业务拒绝可记录 failed，超时、不可信响应及发送过程中断记录 unknown。兼容旧 bool 回调时，True 只表示调用方确认成功，False 保守映射 unknown，不能据此推断“绝对没送达”。

unknown 不自动重发。用户可追加“已收到”确认，或明确确认“未收到”后发起补送；重复确认不产生额外发送，补送尝试和人工判断均保留。恢复核对实例和消息渠道标识；已绑定渠道发生变化时停止发送，恢复原渠道后才能 retry，本批不支持改投渠道。原任务无渠道时，首次显式 retry 可绑定当前渠道并追加事件。服务成功响应表示服务确认接收，不能证明真人阅读；人工确认标明其来源。

### Monitor 与旧数据

新闻观察、原指纹、目标日期、重试次数、模型结果及入池/低权重丢弃/隔离决议进入执行记录。已冻结的因子在 JSON 投影失败后直接重试落盘；只有所需投影确认写入后才更新已处理状态。缓冲成功而去重写入失败时按原指纹核对，不能重复追加因子；未完成记录先恢复，即使新闻已从源列表消失。

保留原评级、指纹算法、数量限制、模型失败重试预算和毒新闻隔离。存储失败与模型解析失败分开记录，不因磁盘问题耗尽解析预算。原 JSON 文件继续作为兼容投影；初次接入核对已有去重、缓冲和隔离内容，损坏或冲突须提示，不能默默当空文件重新分析。

历史 Daily 没有完整快照时，不自动从 Markdown 或新行情拼造旧研究。原“日报＋当日 Memory”完整历史记录沿用旧幂等跳过并提示缺少恢复凭据；历史半成品须人工处理。dry-run 不建立恢复库、不写投影、不补送、不更新审计；retry、confirm 和 abandon 仅预览，不能追加事件。dry-run 仍可能请求模型或网络，与原使用边界一致。

保留 `QuantAgent()` 和原 Python/CLI 入口。新增 `--mode recover --action status|retry|confirm-sent|confirm-not-sent|abandon --run-id <任务编号>`：status 为只读，retry 补可安全重试步骤；两个 confirm 动作只追加确认，confirm-not-sent 后须显式 retry 才补送。abandon 还必须给出 --reason，保留全部快照和未完成事实，之后拒绝 retry，不能伪报成功或撤回已产生的副作用。status 可省略编号列出未完成任务，其他动作必须指定编号；非法转换和正在被另一进程执行的任务拒绝修改。

## 新增依赖

仅使用已安装运行依赖和 Python 标准库 SQLite/文件锁能力。新增具体存储只被 bootstrap 引用；业务与工作流依赖公开契约和所属操作，允许边由能力登记精确声明。恢复适配器不借用其他模块私有锁或直接写其他模块数据库。

本批实施会同步引擎、平台、审计与受影响测试 README；共同规范只在共同规则确有变化时修改。书面规范阶段没有运行接口或数据变化，因此不把拟实现行为提前写成模块当前状态。

## Implementation Plan

以下文件和接口均为待实现安排。按 Task 1 → 5 执行；每批先证明失败，再实现、验收和单独提交。不重新拆目录、引入任务队列或重写已有插件。

### 文件与职责

| 文件 | 职责与所属能力 |
| --- | --- |
| 新建 `quantagent_platform/recovery/__init__.py`、`contracts.py` | 空包入口登记 `recovery-package`（无公开导出）；恢复数据／ports 登记 `recovery-contracts`，不统一导出实现 |
| 新建 `quantagent_platform/recovery/rules.py` | 快照校验、状态转换、Memory 目标及审计载荷冻结；登记 `recovery-domain` |
| 新建 `quantagent_platform/recovery/sqlite_store.py`、`README.md` | 本机执行记录及三类锁；登记 `recovery-storage`，目录资产由它拥有，三个能力共用该 README |
| 修改 `quantagent_platform/legacy_ports.py`、`legacy_bootstrap.py`、`__init__.py` | 追加可选 ports 与惰性恢复工厂；保持原能力归属 |
| 新建 `quantagent_platform/legacy_daily_recovery.py`、`legacy_monitor_recovery.py`、`legacy_recovery_actions.py` | 日报、新闻及人工恢复编排；均登记到现有 `legacy-workflows` |
| 修改 `agent_engine.py`、`signal_audit.py` | 原数据所属方提供受控投影、消息结果和审计操作；不移动原公开入口 |
| 新建 `tests/support/recovery_fixtures.py`，测试见各 Task | 合成快照及隔离引擎；不从其他测试用例导入支持代码 |

新增能力只在实际源文件出现时登记。仅新增这些精确边：legacy-engine/legacy-ports → recovery-contracts；legacy-workflows → recovery-contracts/recovery-domain；legacy-composition → recovery-storage；recovery-domain → recovery-contracts；recovery-storage → recovery-contracts/recovery-domain。适配器只使用公开校验函数，业务不引用 sqlite_store。原能力之间的允许边、豁免、扫描范围及正式样本不变。

### Task 1：冻结契约、本地执行记录与锁

**Files:** 新建上表 recovery 四个源文件及 README、`tests/unit/test_recovery_rules.py`、`tests/contract/test_recovery_store.py`、`tests/architecture/test_recovery_boundaries.py`、`tests/support/recovery_fixtures.py`；修改 `docs/architecture/components.json`、`tests/README.md`、`tests/unit/README.md`、`tests/contract/README.md`、`tests/architecture/README.md`、`tests/support/README.md` 及本文。

**Interfaces:** 在 contracts 定义 `JsonObject = dict[str, Any]`、`TaskKind = Literal["daily", "monitor"]`、`RecoveryAction = Literal["status", "retry", "confirm-sent", "confirm-not-sent", "abandon"]`、`SCHEMA_VERSION = 1`；异常为 `RecoveryError(RuntimeError)` 及其子类 `RecoveryInvalidState`、`RecoveryConflict`、`RecoveryBusy`。

- frozen 数据类：`FrozenSnapshot(version: int, instance_id: str, run_id: str, kind: TaskKind, date: str, created_at: str, payload_json: str, sha256: str)`；`RecoveryEvent(event_id: str, step: str, status: str, occurred_at: str, detail: JsonObject)`；`ExecutionRecord(snapshot: FrozenSnapshot, revision: int, state: Literal["pending", "completed", "abandoned"], steps: dict[str, str], events: tuple[RecoveryEvent, ...])`。
- 结果类：`StepResult(status: Literal["succeeded", "failed", "needs_review", "superseded"], detail: JsonObject)`；`DeliveryResult(status: Literal["confirmed", "failed", "unknown", "not_configured"], source: Literal["provider", "legacy", "manual", "configuration"], channel_id: str | None, error_code: str | None)`。
- `RecoveryStore` protocol：只读 `instance_id: str`；`get(run_id: str) -> ExecutionRecord | None`；`find_daily(date: str) -> ExecutionRecord | None` 返回本实例同日最新记录；`list_open(kind: TaskKind | None = None) -> list[ExecutionRecord]`；`create(snapshot: FrozenSnapshot) -> ExecutionRecord`；`append_event(run_id: str, event: RecoveryEvent, *, expected_revision: int) -> ExecutionRecord`；`lock(scope: Literal["daily", "monitor", "projection"]) -> ContextManager[None]`，默认不等待，被占用抛 RecoveryBusy。
- `RecoveryStoreFactory.__call__(daily_dir: str, *, dry_run: bool = False) -> RecoveryStore`；实现 `SQLiteRecoveryStore` 使用同一构造签名。实例标识取规范化绝对目录字符串的 SHA-256，不保存配置秘密；构造不打开库或锁文件，查询缺库返回空。
- rules 公开函数：`freeze_snapshot(*, instance_id: str, run_id: str, kind: TaskKind, date: str, created_at: str, payload: JsonObject) -> FrozenSnapshot`；`validate_snapshot(snapshot: FrozenSnapshot) -> None`；`transition(record: ExecutionRecord, event: RecoveryEvent) -> ExecutionRecord`；`build_memory_target(state: JsonObject, capsule: JsonObject, clamp: Callable[..., str]) -> JsonObject`；`freeze_audit_payload(snapshot: FrozenSnapshot, steps: dict[str, str], at: str) -> JsonObject`。
- 快照正文用 `ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False` 序列化，哈希取实际 UTF-8 字节；时间必须带时区。Daily 正文键为 `signal_id, started_at, report, message, capsule, metrics, compact_news, analysis, previous_memory, memory_target, report_preimage, memory_preimage, audit_facts, audit_preimage, channel_id`。Monitor 正文键为 `news, news_id, fingerprint, target_date, observed_at`；推理结果和次数随后追加事件。
- step 名为 `report/message/memory/audit/model/buffer/dedup/fingerprint/quarantine/audit_payload/task`；本地状态按规范，消息状态按 DeliveryResult，audit_payload 只允许首次 frozen。task 事件 completed/abandoned/retry_requested 分别完成、终止、显式请求恢复；完成条件未满足不能 completed，abandoned 不接受后续执行事件。审计冻结结果键为 `run, signal, factors, expected_canonical_signal_id`，首次依据实际 steps 填交付标记，后续不改写。
- 测试支持公开构造器为 `daily_payload(date: str = "2026-10-03") -> JsonObject`、`news_payload(date: str = "2026-10-03") -> JsonObject`；Task 2 追加 `isolated_engine(root: Path, *, dry_run: bool = False, wecom_url: str | None = "https://example.invalid/webhook") -> ContextManager[Any]`，使用合成配置、阻断外部请求并在退出时恢复环境及绑定。

- [x] **RED tests:** `test_snapshot_is_frozen` 用 `self.assertRaises(FrozenInstanceError)` 验证字段不可改、改动正文后 `self.assertRaises(RecoveryInvalidState)`；`test_invalid_version_hash_and_instance_are_rejected` 用 version=2、错误哈希及另一实例逐项断言拒绝、`self.assertEqual(saved_snapshot, original_snapshot)`；`test_constructor_and_status_do_not_create_storage` 断言 `self.assertFalse(root.exists())`、`self.assertEqual(store.list_open(), [])`。
- [x] **RED tests:** `test_event_append_is_atomic_and_revision_checked` 断言事件与当前状态同时提交、重复同 event_id 同载荷不增加事件、不同载荷或旧 revision 抛 RecoveryConflict；`test_unknown_message_is_not_retryable_without_confirmation` 断言 unknown 不能直接进入发送 running，abandoned 不能恢复；`test_memory_target_and_audit_freeze` 断言滚动日期去重且最多 7 条、unknown/superseded 对应 wecom_sent/memory_saved 均为 False、两次冻结请求不能改载荷。运行 `python -m unittest tests.unit.test_recovery_rules tests.contract.test_recovery_store tests.architecture.test_recovery_boundaries -v`；RED 须证明缺失行为，不能把导入／环境错误算证据，新 API 可先用可导入签名壳，壳不单独提交。
- [x] **Implement:** 建立 execution_records/recovery_events 两张表，PRAGMA user_version=1、实例字段、不可变快照、唯一事件键、revision 比较更新；事件和当前状态在一笔短事务中提交，连接显式关闭。查询使用 mode=ro，既有库不自动修复或迁移未知版本；dry-run 禁止写入。锁采用各平台标准库 OS 锁，进程死亡释放，projection 锁不跨模型／网络调用；任务完成校验遵循已批准规范。
- [x] **GREEN:** 重跑上列命令，全部通过；规则与 contracts 静态断言不含 IO／SDK，存储只能依赖登记的公开接口。同步登记、七项 README 和本文命令／环境／源码版本／结果。
- [x] **Commit:** 仅暂存本 Task Files 中实际改动，`git commit -m "feat: add immutable recovery journal and locks"`；运行本节末的门禁并保留报告。

### Task 2：所属文件、消息及审计的恢复接口

**Files:** 修改 `agent_engine.py:38-111,339-394,456-566,818-902`、`signal_audit.py:100-331`、`quantagent_platform/legacy_ports.py`、`quantagent_platform/legacy_bootstrap.py`、`quantagent_platform/__init__.py`、`quantagent_platform/recovery/rules.py`、`tests/support/recovery_fixtures.py`、`tests/support/README.md`、`docs/architecture/components.json`、`docs/architecture/legacy-engine/README.md`、`quantagent_platform/README.md`、`sql/README.md`、`quantagent_platform/recovery/README.md`、`tests/README.md`、`tests/contract/README.md` 及本文；新建 `tests/contract/test_recovery_ports.py`。行号均以 R001 基线为准。

**Interfaces:** 消费 Task 1 类型；在 legacy_ports 增加 `configure_legacy_recovery_factory(factory: RecoveryStoreFactory) -> None`、`get_legacy_recovery_factory() -> RecoveryStoreFactory`；bootstrap 提供 `build_legacy_recovery_store(daily_dir: str, *, dry_run: bool = False) -> RecoveryStore`、`install_legacy_recovery_factory() -> None`，指定包启动入口仅安装工厂。

- DailyPorts 尾部可选字段均默认 None：`recovery: RecoveryStore | None`、`capture_inputs: Callable[[str], JsonObject] | None`、`prepare_audit: Callable[[JsonObject], JsonObject] | None`、`project_report/project_memory: Callable[[FrozenSnapshot], StepResult] | None`、`commit_audit: Callable[[JsonObject], JsonObject] | None`、`send_message: Callable[[str], DeliveryResult | bool] | None`、`channel_id: Callable[[], str | None] | None`。没有 recovery 的既有显式 ports 仍执行原工作流；正式引擎始终注入完整新接口，绑定失败不能降级绕过恢复。
- QuantAgent 新公开方法与上述回调同签名：`capture_daily_inputs(date)`、`prepare_recovery_audit(draft)`、`project_daily_report(snapshot)`、`project_daily_memory(snapshot)`、`commit_frozen_audit(payload)`、`send_wecom_result(text)`、`recovery_channel_id()`。capture 返回 `memory_state, report_preimage, memory_preimage, audit_preimage`，不存在文件的 preimage 为 None；audit_preimage 是当日原 canonical signal_id。draft 键为 `date, started_at, capsule, metrics, compact_news, previous_memory, analysis`；prepare 返回 `{run, signal, factors}` 的研究事实，交付标记留到首次审计事件才填入。
- SignalAuditStore 增加 `validate_completed_signal(run: Mapping[str, Any], signal: Mapping[str, Any], factors: list[Mapping[str, Any]] | None = None) -> None`，仅校验不连接；`record_recovered_signal(run: Mapping[str, Any], signal: Mapping[str, Any], factors: list[Mapping[str, Any]] | None = None, *, expected_canonical_signal_id: str | None) -> dict[str, Any]`，在原审计事务中核对 canonical 前像，变化时只补非规范旧信号。原 record_completed_signal 签名、正常强制运行语义、SQL 迁移及类型别名保持。
- AuditStore protocol 同步声明上述两项新操作及既有 `get_canonical_signal(signal_date: str, asset: str = "BTC", decision_horizon: str = "1d") -> dict[str, Any] | None`。旧自定义存储若缺少恢复接口，进入新路径前明确拒绝，不能交付后才发现；原直接调用接口不变，新增方法使用同一已注入实例。派生类对旧 record_completed_signal 的覆盖不会自动成为新方法的覆盖，契约测试须分别证明两种公开操作仍消费自定义存储。

- [x] **RED tests:** `test_unicode_projection_hash_matches_written_bytes` 使用中文和换行，`self.assertEqual(report_bytes, frozen_report.encode("utf-8"))`，JSON 目标与按冻结 memory_target 序列化的字节相同，第二次投影零替换；`test_projection_conflict_and_replace_failure_preserve_bytes` 断言 `self.assertEqual(result.status, "needs_review")`、替换失败保留旧字节；`test_old_memory_is_superseded_without_rolling_duplicate` 断言 `self.assertEqual(result.status, "superseded")`、新胶囊及重复同日的 rolling_7d 不变。
- [x] **RED tests:** `test_native_and_legacy_delivery_truth` 断言 errcode=0 → confirmed、明确业务拒绝 → failed、超时／不可信响应及旧 bool False → unknown、无渠道 → not_configured，旧 bool True → confirmed；`test_audit_preflight_idempotency_and_canonical_guard` 断言无效载荷不建库、同冻结编号实际行数不增、旧补账不替换新 canonical。运行 `python -m unittest tests.contract.test_recovery_ports tests.test_signal_audit tests.contract.test_legacy_ports -v`，核对 RED 原因。
- [x] **Implement:** 文件由原所属方严格读取、在 projection 锁内核对前像并写同目录唯一临时文件后原子替换；JSON 沿用 ensure_ascii=False、indent=2，Memory 沿用原裁剪规则，哈希计算与落盘共用同一 UTF-8 字节，报告不额外转换换行。相同目标先识别已完成；较新 Memory 返回 superseded。新消息 API 每次最多一次发送，只保存渠道标识哈希和错误代码；HTTP 200 且整数 errcode=0 为 confirmed、整数非零为 failed，其他不可信响应为 unknown。push_to_wecom 原 bool 签名保留，旧回调覆盖由绑定层识别并保守转换，不能旁路或发两次。
- [x] **GREEN:** 上列命令全过；实际 SQLite 测试检查 run/signal/factor 数量和 canonical，而非只检查 mock。在独立 `python -B -S` 中再次验证原审计可用，未加载插件平台；所有注入在测试后经公开 getter/configure 恢复，同步 README 和本文。
- [x] **Commit:** 仅暂存本 Task Files 中实际改动，`git commit -m "feat: add guarded recovery projections and delivery results"`；运行门禁。

### Task 3：Daily 恢复与人工命令

**Files:** 新建 `quantagent_platform/legacy_daily_recovery.py`、`quantagent_platform/legacy_recovery_actions.py`、`tests/integration/test_daily_recovery.py`；修改 `quantagent_platform/legacy_workflows.py:164-315`、`agent_engine.py:881-930`、`docs/USAGE.md`、`tests/test_idempotency_error_isolation.py`、`tests/test_dry_run.py`、`tests/integration/audit/test_signal_audit_integration.py`、`tests/contract/test_legacy_ports.py`、`tests/architecture/test_legacy_boundaries.py`、`docs/architecture/components.json`、`docs/architecture/legacy-engine/README.md`、`quantagent_platform/README.md`、`quantagent_platform/recovery/README.md`、`tests/README.md`、`tests/integration/README.md`、`tests/integration/audit/README.md` 及本文。

**Interfaces:** 消费 Task 1/2 ports；提供 `run_daily_recovery(ports: DailyPorts) -> JsonObject`、`resume_daily(ports: DailyPorts, record: ExecutionRecord, *, explicit_retry: bool = False) -> JsonObject`；`run_recovery_action(store: RecoveryStore, *, action: RecoveryAction, run_id: str | None = None, reason: str | None = None, dry_run: bool = False, daily: DailyPorts | None = None, monitor: MonitorPorts | None = None) -> JsonObject`；QuantAgent 增加 `daily_ports() -> DailyPorts`，原 run_daily_pipeline() 委托原工作流门面。

- [x] **RED tests:** `test_invalid_capsule_or_snapshot_failure_has_no_delivery` 断言日报、消息、Memory、审计均未写；`test_resume_after_each_daily_boundary_reuses_snapshot` 对 report/message/memory/audit 的失败及状态未确认用 subTest，重建引擎后断言固定 run_id/signal_id、fetch/model 零新调用、已完成步骤不重复。运行 `python -m unittest tests.integration.test_daily_recovery tests.test_idempotency_error_isolation tests.integration.audit.test_signal_audit_integration -v`，核对 RED。
- [x] **RED tests:** `test_unknown_confirmation_and_explicit_retry` 断言 unknown 重跑及 confirm-not-sent 均保持原发送次数，随后 retry 满足 `self.assertEqual(attempts_after, attempts_before + 1)`，confirm-sent 和重复确认不发送；`test_audit_payload_remains_frozen_after_later_confirmation` 断言 `self.assertEqual(audit_run["wecom_sent"], 0)` 始终保持、后续人工确认只追加事件；`test_first_channel_binding_and_channel_change` 断言未配置任务完成后正常跳过、首次显式 retry 绑定并发送、渠道改变拒绝发送。
- [x] **RED tests:** `test_status_without_configuration_and_dry_actions_are_read_only` 子进程无密钥／缺目录执行 status，断言零创建；已有快照下 dry-run 的五种 action 断言文件与事件不变；`test_force_legacy_partial_and_abandon_rules` 断言未完成不能被 FORCE 绕过、完成／明确 abandon 后新编号、完整旧历史继续精确 skipped、旧半成品 needs_review、abandon 无 reason 或之后 retry 均拒绝且历史保留。
- [x] **Implement:** Daily 锁覆盖任务选择至本次执行；首次先严格读前像、研究和校验，然后提交完整快照，交付仍按 report → message → memory → audit。每步先追加 running、执行所属操作、再追加实际结果；本地 running 恢复核对投影，消息 running 恢复为 unknown。首次审计前单独追加冻结载荷事件，后续仅提交该载荷；memory failed 阻止审计，superseded 允许据实补账，message unknown 不阻止必要本地步骤。
- [x] **Implement:** CLI 按已批准 action／run-id／reason 校验。status 与不需研究的确认／终止不构造 QuantAgent；retry 才按需构造完整 ports，每次取得对应任务锁，不启动长期 Monitor 循环。正常成功保留 report/capsule/audit，重复完成保留原 skipped 字典；未完成附 status/run_id，明确阻塞步骤。原无效胶囊测试改为零交付断言；顺序测试改为预检 capsule 在先、交付顺序不变，审计注入改为验证 commit_frozen_audit，不能删掉原验收意图。
- [x] **GREEN:** 上列命令及 `python -m unittest tests.contract.test_legacy_ports tests.architecture.test_legacy_boundaries -v` 全过；原 TaggedStore 测试同时覆盖原审计直调与新增恢复操作，保留实际 SQLite 和质检注入断言。HTTP 和原 Python 别名不变，新静态允许目标仅为已登记契约／工作流。同步当前 README、USAGE 与本文，`git commit -m "feat: resume frozen daily runs with manual recovery controls"`；仅暂存本 Task Files，运行门禁。

### Task 4：Monitor 持久重试与兼容投影

**Files:** 新建 `quantagent_platform/legacy_monitor_recovery.py`、`tests/integration/test_monitor_recovery.py`；修改 `quantagent_platform/legacy_workflows.py:6-160`、`quantagent_platform/legacy_ports.py`、`quantagent_platform/legacy_recovery_actions.py`、`agent_engine.py:848-873`、`tests/support/recovery_fixtures.py`、`tests/support/README.md`、`tests/test_idempotency_error_isolation.py`、`tests/contract/test_legacy_ports.py`、`tests/architecture/test_legacy_boundaries.py`、`docs/architecture/components.json`、`docs/architecture/legacy-engine/README.md`、`quantagent_platform/README.md`、`quantagent_platform/recovery/README.md`、`tests/README.md`、`tests/integration/README.md` 及本文。

**Interfaces:** MonitorPorts 尾部新增 `dry_run: bool = False`、`recovery: RecoveryStore | None = None`、`capture_state: Callable[[str], JsonObject] | None = None`、`project_news: Callable[[ExecutionRecord, Literal["buffer", "dedup", "fingerprint", "quarantine"]], StepResult] | None = None`；所属方法 `capture_monitor_state(date: str) -> JsonObject` 返回 `buffer, dedup, fingerprint, quarantine`，`project_news_record(record: ExecutionRecord, projection: Literal["buffer", "dedup", "fingerprint", "quarantine"]) -> StepResult`；工作流 `run_monitor_recovery(ports: MonitorPorts) -> None`、`resume_news(ports: MonitorPorts, record: ExecutionRecord) -> JsonObject`。QuantAgent 提供 `monitor_ports() -> MonitorPorts`；人工 retry 调用 resume_news，只恢复指定任务。model 事件 detail 使用 `attempts, raw_result, factor, decision`；attempts 为原解析失败次数，decision 取 pooled/low_weight_discarded/quarantined，失败未达预算仍 pending。

- [ ] **RED tests:** `test_pending_news_survives_midnight_and_source_removal` 先冻原因子、模拟落盘失败和次日空 RSS，断言写原 target_date、`self.assertEqual(model_calls, 1)`；`test_buffer_ack_then_dedup_failure_has_one_factor` 断言 `self.assertEqual(matching_factor_count, 1)`、dedup/fingerprint 都最终存在；`test_storage_failure_does_not_spend_parse_budget` 断言写入失败前后解析 attempts 相同。运行 `python -m unittest tests.integration.test_monitor_recovery tests.test_idempotency_error_isolation tests.contract.test_legacy_ports -v`，核对 RED。
- [ ] **RED tests:** `test_low_weight_and_poison_quarantine_finish_only_after_projection` 断言低权重不入池但完成去重，达到原预算后先成功写 quarantine 才处理完成，解析失败未达预算仍可重试；`test_legacy_malformed_or_conflicting_news_files_stop` 对三类旧 JSON 和 buffer 的错误类型／冲突用 subTest，断言无新模型调用、不覆盖旧字节；`test_monitor_dry_run_has_no_recovery_or_projection_writes` 断言没有恢复库、锁文件或 JSON 变更；`test_recovery_respects_original_cycle_budget` 断言待重推与新新闻合计不超过 max_news_per_cycle，纯投影不占模型配额。
- [ ] **Implement:** 先取得 Monitor 执行锁，严格核对旧投影，再恢复待办，最后处理新观察；旧投影只沿用已知去重／次数，不拼造缺少原新闻的旧失败任务。观察先落盘、模型结果和校准决议独立冻结，投影逐个对账，不先改内存 processed 集合。中断于模型 running 可重试但不伪造已保存推理；已冻结结果禁止重推。持久 attempts 只计模型／解析失败，存储异常必须在该计数块外；预算、评级、指纹、数量及 pruning 使用原回调和限值，本轮恢复重推与新推理共用原限额；buffer 同指纹同结果视为已投影，不同结果 needs_review。
- [ ] **GREEN:** 上列命令通过；旧测试中 mock 写入改为包装真实临时文件写入，保留原重试次数、隔离及去重断言。CLI retry 不抓新新闻、不进入 sleep 循环。同步 README 与本文，`git commit -m "feat: recover pending monitor projections without repeated inference"`；仅暂存本 Task Files，运行门禁。

### Task 5：跨进程故障、兼容性与最终验收

**Files:** 新建 `tests/integration/test_recovery_processes.py`；按用例补齐 `tests/support/recovery_fixtures.py`、`tests/architecture/test_recovery_boundaries.py`、`tests/README.md`、`tests/integration/README.md`、`tests/architecture/README.md`、`tests/support/README.md` 及本文；只在新失败指向产品缺陷时修改前四批所属文件，逐项记录原因。

**Interfaces:** 仅使用 Task 1–4 公开接口；不增加生产故障注入参数。测试在子进程用端口包装器 `os._exit(23)` 中断指定边界，网络／模型均为合成替身，SQLite 和原子替换使用真实临时存储。

- [ ] **RED tests:** `test_process_death_releases_locks_and_reconciles_effects` 覆盖 report、message、memory、audit 提交后／事件确认前退出，`self.assertEqual(crashed_process.returncode, 23)`、新进程可取得锁、原编号保持、消息 unknown 不重发、`self.assertEqual(after_audit_counts, before_audit_counts)`；`test_concurrent_daily_and_monitor_respect_scoped_locks` 用 `self.assertRaises(RecoveryBusy)` 验证两个 Daily 或两个 Monitor 拒绝并发，同一 Daily 与 Monitor 可同时推理、短 projection 锁串行，旧 Memory 不覆盖新日期；同步屏障不用猜测性长 sleep。
- [ ] **Implement/fix:** 先重现并保留 RED 原因，再在所属模块修正；不放宽门禁或替换真实存储为 mock。全离线基线原 341 项、7 项环境跳过只作历史参照；记录本次实际发现、通过、失败和跳过理由，不能预填结果。
- [ ] **GREEN targeted:** `python -m unittest tests.integration.test_recovery_processes tests.integration.test_daily_recovery tests.integration.test_monitor_recovery tests.contract.test_recovery_store tests.contract.test_recovery_ports tests.architecture.test_recovery_boundaries -v` 全通过；再运行 `python -m unittest discover -s tests -v` 和架构门禁。全套必须非零发现、0 失败；真实可选依赖按原跳过条件解释。
- [ ] **GREEN compatibility:** 单独核对原导出／类型身份、CLI help 与三种原 mode、HTTP 状态／字段／权限、固定配方及正式资产哈希；原 162 项正式资产字节保持，旧能力之间的允许关系不变。原 34 项定义重新按本批范围核对：仅已列明的日报预检／恢复、Monitor 投影确认及消息分类允许行为变化，原公开签名及非目标行为保持，不能继续沿用 D006 的实现 AST 全部不变要求。Windows 本地与未来 Linux CI 结果分别记录；真实服务、远端 CI、部署与生产未跑就写未跑。
- [ ] **Review/commit:** 沿用 Native，由本会话完成各批后请求一次新的整分支独立审查，记录结论并修复阻断项；补齐实际源码／文档提交及回滚证据后 `git commit -m "test: verify R001 process recovery and compatibility"`，仅暂存本 Task 实际修改，再复核门禁和工作树。保留用户原有删除，不推送、合并或部署。

### 每批命令与记录

所有命令从当前工作树根执行，使用仓库外 `C:/Users/yj/AppData/Local/Programs/Python/Python312/python.exe`；PowerShell 设置 PYTHONUTF8=1、PYTHONIOENCODING=utf-8、PYTHONPATH 为仓库及现有 `.venv/Lib/site-packages`、PATH 含 `D:/Git/cmd`。Git 每次采用命令级 `-c "safe.directory=D:/CryptoVault/Local repository/QuantAgent-architecture-guardrails"`；提交前检查暂存清单及 `git diff --cached --check`，不用 add -A。

门禁命令：`python -m tools.architecture --base-ref 9c09e12e6bf82c0e1fe3845ee1bf71cd1941a6ea --branch feature/r001-recovery-resume --report artifacts/recovery/r001/task-N-gate.json`。本地日志在同一忽略目录；通过要求无违规、无循环、无文档错误且 Import Linter 返回 0。登记真实新增能力不算放宽原边界，不能恢复已清除的问题。

每批在本文测试证据中追加命令、环境、实际源码提交、结果及未测范围；README 只写当前已实现接口，不重复计划。计划自查映射：快照／协议／锁 → Task 1；投影／发送／审计 → Task 2；Daily／确认／旧历史／FORCE → Task 3；Monitor／隔离／跨日 → Task 4；进程退出／并发／整套兼容 → Task 5。上方五项 Review Focus 均有指定测试。

## 测试证据

已执行排查：2026-10-03，Windows、Python 3.12.8、UTF-8，源码提交 `9c09e12e6bf82c0e1fe3845ee1bf71cd1941a6ea`。命令为 PowerShell 将内存探针文本传给 `python -B -`；PYTHONPATH 含仓库和已有 venv，外部服务被阻断，只使用临时目录。原探针归档于忽略的 `artifacts/recovery/r001/probe.txt`，没有作为产品代码保留。

实际四项：未确认消息后重跑 skipped，仅一次推送尝试，审计 wecom_sent=0；审计失败后存储恢复仍 skipped，未建审计库；Memory 写失败时日报存在、消息尝试一次、旧 Memory 字节保留；新闻缓冲失败后抓取两轮仅推理一次，缓冲及去重文件均不存在。均为当前缺口复现，不是修复通过。

实施完成必须验证以下正反例：

| 场景 | 验收结果 |
| --- | --- |
| 日报、Memory、审计任一边界失败或进程中断 | 新进程恢复原快照；已完成内容保持；不重复研究、不漏任务 |
| 审计提交成功后状态写入失败 | 重试同一编号，实际 SQLite 信号/因素行数不增加 |
| 消息超时或发送后状态写入失败 | 保留 unknown；默认不自动补送；确认动作与显式补送可核验 |
| 历史恢复与新胶囊、强制重跑冲突 | 较新状态保持，旧快照及人工决定可追踪 |
| 缓冲、去重、隔离投影失败及源列表更新 | 待处理任务仍可恢复，无重复因子，不消耗解析预算 |
| 并发启动、损坏状态或不支持的协议版本 | 锁与校验拒绝越权/错误继续，旧有效字节保留 |
| 完整任务重跑、正常路径、旧历史和 dry-run | 原入口、正常结果、幂等与零业务写入约束保持 |
| 全离线套件、Python/CLI/HTTP/固定配方及架构门禁 | 必需回归通过；原资产和数据权限保持，无新增违规或放宽规则 |

本阶段为文档变更：产品完整套件未重跑，因为运行源码未修改。设计自查已核对占位、矛盾、范围及歧义，补齐交付标记的二阶段冻结、可选消息、Memory superseded、渠道变更和人工终止规则。提交前命令 `python -m tools.architecture --base-ref 9c09e12e6bf82c0e1fe3845ee1bf71cd1941a6ea --branch feature/r001-recovery-resume --report artifacts/recovery/r001/design-gate.json` 实际通过：60 模块、0 存量、无循环或错误，Import Linter 返回 0。报告和日志保留在该忽略目录；提交后用同一命令核对。真实新闻、模型、消息、Linux、远端 CI、部署和生产均未执行本批验收。

实施计划记录：书面规范 `2a29b69ef0fd88805f571339603530c69ed4b3ec` 已批准；2026-10-03 在相同 Windows／Python 3.12.8／UTF-8 环境完成计划自查，核对规范覆盖、步骤可执行性、接口一致性、五项 Review Focus 和文档篇幅。修正草案中的文件路径、旧自定义审计接口接入、前像保护与模型预算说明；所有实施复选框仍未勾选。将上列门禁报告路径改为 `artifacts/recovery/r001/plan-gate.json` 后实际通过：60 模块、0 存量、无循环或错误、Import Linter 返回 0。仅更新本文，产品和测试源码均未改、完整产品套件未重跑；提交后复核同一门禁，详细收据保留在同目录的 plan-review.json。

实施基线：2026-10-03，Windows／Python 3.12.8／UTF-8，在计划提交 `f38ede46eef828d9eec7ba32798139f09e00fe04` 上运行 `python -m unittest discover -s tests -v`：341 项、0 失败、7 项原环境跳过，69.663 秒。Task 1 定向命令见恢复 README：实现前 9 项因缺少公开功能而失败，实现后 9 项通过。Task 1 在计划提交 f38ede4 上的工作差异执行完整命令：350 项、0 失败、7 项原环境跳过，70.355 秒；task-1-gate.json 为 64 模块、0 存量、0 循环／错误、Import Linter=0。空包入口单独登记为无公开导出的 recovery-package，解决分层工具的父包重叠，不改变扫描规则或豁免。外部服务和生产仍未验证。

Task 2：在源码 f64a30e 的工作差异运行定向命令及静态边界，28 项通过；完整套件 355 项、0 失败、7 项原环境跳过，70.183 秒。环境仍为 Windows／Python 3.12.8／UTF-8。task-2-gate.json：64 模块、0 存量／循环／错误，Import Linter=0。新增公开审计接口仍通过独立 `python -B -S` 的实际 SQLite 验证；现有显式 ports 流程尚未切换。

Task 3：在提交 `0bb853758aaa0372fde630bca13cc9ae52750eb5` 的工作差异验证新 Daily／原幂等／审计／契约／边界 34 项通过；补核 dry-run 与 Daily 13 项通过。完整套件最终 362 项、0 失败、7 项原环境跳过，74.725 秒；门禁 66 模块、0 存量／循环／错误，Import Linter=0。完整回归发现另一处旧胶囊顺序断言，已按批准的预检行为更新并保留零提前交付断言；首轮失败日志保存为 task-3-full-red.log。人工未收到后普通重跑的失败用例已先复现、再修正为明确 retry 才可发。环境／未测范围同前。

## 回滚方式

只回退本批代码和文档提交；保留并备份新增恢复库、快照及事件，不删除原日报、Memory 或审计。回退不会撤回已发消息，旧代码也不认识新恢复记录；有未完成任务时先停下自动执行、核对状态，再选择继续新版恢复或人工处理。原用户文件删除不纳入本批提交。

## 遗留问题

首次协议仅支持单机同一实例。历史资料不足、消息未知及人为改动不能自动判真；恢复记录不能证明真实送达或物理灾难恢复。完成记录本批保留，不自动清理，后续需单独制定保留/归档规则。书面规范和实施计划均已批准；沿用本会话的当前工作树、Native 和逐批验收方式。
