# 离线验证与验收

## 职责与边界

使用固定样本与替身验证原公开 Python、CLI、HTTP、配方、权限、审计与恢复行为。测试、CI 和生产证据分开记录。按 [开发与测试归属](../docs/DEVELOPMENT_TESTING.md) 首批只迁移六个文件，不以目录位置推断完全隔离的单元测试。

## 文件导航

| 分类 | 实际入口 | 试点范围 |
| --- | --- | --- |
| 模块规则 | [unit](unit/README.md) | SEC 分析、P5 严格解析与策略 |
| 公开契约 | [contract](contract/README.md) | SEC 标准化、审计 SQL schema、API 类型与旧入口身份 |
| 跨组件 | [integration](integration/README.md) | SEC 工作流、P5 CLI/HTTP 与存储注入兼容、引擎审计、运行器及 API 组装兼容 |
| 架构门禁 | [architecture](architecture/README.md) | 依赖、文档及启动规则正反例 |
| 共享支持 | [support](support/README.md) | ROOT、SEC/P5 合成构造器、API 契约捕获、[fakes](support/fakes/README.md) |
| 静态样本 | [fixtures](fixtures/README.md) | 原 JSON/CSV/TXT、固定 P5 与重构前 HTTP 兼容预期 |

剩余平铺文件及主要类别如下。混合范围保留，后续随对应能力整改，不在本批强拆：

| 文件 | 主要类别与混合范围 |
| --- | --- |
| [test_agent_runtime.py](test_agent_runtime.py) | 集成：Agent 与固定配方协作，兼含入口契约 |
| [test_bt_plugins.py](test_bt_plugins.py) | 契约/集成混合：bt 子进程协议、权限、失败与可选真实后端 |
| [test_daily_plugins.py](test_daily_plugins.py) | 规则/集成混合：日报插件与固定样本 |
| [test_dry_run.py](test_dry_run.py) | 集成：旧引擎 dry-run，模型与网络替身 |
| [test_idempotency_error_isolation.py](test_idempotency_error_isolation.py) | 集成：旧引擎幂等及错误隔离 |
| [test_manifest_spec.py](test_manifest_spec.py) | 契约：manifest 格式、输入与拒绝条件 |
| [test_outcome_replay.py](test_outcome_replay.py) | 集成：结果回放与插件 |
| [test_p5_agents.py](test_p5_agents.py) | 契约/集成混合：Agent manifest 与 P5 数据 |
| [test_p5_coordinator.py](test_p5_coordinator.py) | 集成：P5 编排 |
| [test_p5_handoff.py](test_p5_handoff.py) | 契约/规则混合：交接载荷与校验 |
| [test_p5_ledger.py](test_p5_ledger.py) | 规则/存储混合：追加账本与恢复 |
| [test_p5_live_acceptance.py](test_p5_live_acceptance.py) | 可选私有本地验收：原环境开关、固定 P4 数据 |
| [test_p5_manifest.py](test_p5_manifest.py) | 契约：P5 manifest |
| [test_p5_registry.py](test_p5_registry.py) | 集成：登记、持久化与权限 |
| [test_p5_review.py](test_p5_review.py) | 规则/契约混合：复核结果与拒绝条件 |
| [test_p5_worker.py](test_p5_worker.py) | 集成：worker 生命周期、隔离和失败关闭 |
| [test_platform.py](test_platform.py) | 契约/集成混合：平台与 runner |
| [test_qlib_plugins.py](test_qlib_plugins.py) | 契约/集成混合：Qlib 子进程协议、权限与可选真实后端 |
| [test_result_api.py](test_result_api.py) | 集成：HTTP 读取与隔离 |
| [test_run_cancellation.py](test_run_cancellation.py) | 集成：运行取消 |
| [test_sec_client.py](test_sec_client.py) | 契约：SEC transport 替身与失败处理 |
| [test_signal_audit.py](test_signal_audit.py) | 规则/存储混合：审计记录、SQL 与完整性 |
| [test_submission_api.py](test_submission_api.py) | 集成：受控 HTTP 提交 |
| [test_support_paths.py](test_support_paths.py) | 规则：共享仓库定位（三项）与原单文件入口启动回归（一项） |
| [test_task_lifecycle_api.py](test_task_lifecycle_api.py) | 集成：任务生命周期 HTTP |
| [test_thesis_tracker.py](test_thesis_tracker.py) | 规则/集成混合：观点跟踪与样本回放 |

R001 恢复测试入口见 [恢复功能](../quantagent_platform/recovery/README.md)；实际分批结果见 [R001](../docs/features/r001-recovery-resume.md)。

## 对外接口

D006 新边界见 [test_legacy_boundaries.py](architecture/test_legacy_boundaries.py)；实际回调、临时 SQLite、新闻重试恢复、入口哈希与离线 CLI 启动见 [test_legacy_ports.py](contract/test_legacy_ports.py)。原引擎和存储用例保留，验收记录在[D006 分支说明](../docs/features/d006-legacy-workflows.md)。

主命令 `python -m unittest discover -s tests -v` 保持。共享数据由 tests.support 导入，用例文件不作为共享库；原 TestCase 和方法名保持，六项模块前缀映射见 [实施计划](../docs/superpowers/plans/2026-10-02-file-classification.md)。

## 依赖规则

测试使用对应公开产品接口、原替身、标准库和共享支持；产品代码不依赖 tests。生产依赖仍按 [components.json](../docs/architecture/components.json) 管理，不通过测试目录改变边界或豁免。

## 数据与权限

保留临时目录、固定样本、原可执行根和子进程权限；无私人账号种子或新增现场 manual 脚本。QuantAgent 管理公共证据，OpenStock 拥有私人档案、规则、决定与回证，测试支持不得绕过所有者写入。

## 测试与验收

从仓库根运行主命令及 `python -m unittest discover -s tests/unit -t . -v`、contract/integration 同类非零发现命令。子目录命令须加 `-t .` 固定仓库为包根，避免 contract/platform 遮住 Python 标准库 platform。使用仓库外 Python，避免 Qlib 负向权限误判。分类时的用例映射与数量见 [分类批次](../docs/features/file-classification.md)；后续重构新增测试及实际验收见对应分支说明，例如 [D001](../docs/features/d001-runner-composition.md)。

[D002](../docs/features/d002-p5-boundaries.md) 新增纯规则、静态边界、存储注入和真实离线子进程的固定回证比较；合成样本不能替代私有 P4 或现场服务验收。

[D003](../docs/features/d003-api-composition.md) 验证 API 静态边界、共享类型身份、原 HTTP 契约、可选依赖启动、存储授权与 worker 关闭；既有提交和任务用例继续覆盖幂等、取消、失败与重启。

[D004](../docs/features/d004-sec-contracts.md) 增加 SEC 响应契约的静态边界、旧别名及不可变字段、独立模块导入和原字节上限检查；实际启动组装仍允许加载具体插件。

该批还修复全量回归复现的 Windows 原子写入问题；单模块 IO 用例在 [unit](unit/README.md)，并发 HTTP 仍使用原未跳过用例。

[D005](../docs/features/d005-adapter-contracts.md) 增加适配器共享契约的静态边界，以及 [worker ports 契约](contract/test_worker_ports.py)的注入、错误、旧别名、启动和默认配方消费测试；原质检、日报、历史评价及 Qlib/bt 离线用例继续验证消费结果、进程权限和审计。

## 已知限制

当前部分符合，剩余问题见 [精确基线](../docs/architecture/legacy-baseline.json)；平铺测试并非全部纯单元测试。真实 bt/Qlib 和私有 P4 验收保留原开关，跳过不代表通过；本地替身、模拟消息或模型日志不能作为真实调用、CI 或生产证据。
