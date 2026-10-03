# 插件平台与现有功能导航

## 职责与边界

本目录提供插件契约、执行工作流、适配器与启动组装。平铺文件按能力登记分别治理；工作流通过公开接口协作，不取得其他模块的数据写权限。

## 文件导航

- `packet-contracts`：[quantagent_platform.contracts](contracts.py)。
- `signal-report-contracts`：[signal_report_contracts](signal_report_contracts.py)，原信号、质检和报告 Packet 版本标识的共享定义。
- `research-contracts`：[quantagent_platform.research_contracts](research_contracts.py)。
- `sec-contracts`：[quantagent_platform.sec_contracts](sec_contracts.py)。
- `sec-response-contracts`：[sec_response_contracts](sec_response_contracts.py)，不可变原始响应、读取上限与固定来源 URL。
- `plugin-ports`：[quantagent_platform.plugins](plugins.py)。
- `daily-domain`：[quantagent_platform.daily_workflow](daily_workflow.py)。
- `sec-domain`：[quantagent_platform.sec_analysis](sec_analysis.py)。
- `quality-adapter`：[quantagent_platform.builtin_plugins](builtin_plugins.py)。
- `daily-adapter`：[quantagent_platform.daily_plugins](daily_plugins.py)。
- `outcome-adapter`：[quantagent_platform.outcome_plugins](outcome_plugins.py)。
- `thesis-adapter`：[quantagent_platform.research_plugins](research_plugins.py)。
- `isolated-runtime`：[quantagent_platform.isolated_runtime](isolated_runtime.py)。
- `worker-ports`：[worker_ports](worker_ports.py)，原隔离执行结果、服务接口及公开调用入口。
- `worker-composition`：[worker_bootstrap](worker_bootstrap.py)，启动时绑定隔离执行服务工厂。
- `qlib-adapter`：[quantagent_platform.qlib_plugins](qlib_plugins.py)。
- `qlib-adapter`：[quantagent_platform.qlib_worker](qlib_worker.py)。
- `bt-adapter`：[quantagent_platform.bt_plugins](bt_plugins.py)。
- `bt-adapter`：[quantagent_platform.bt_worker](bt_worker.py)。
- `sec-adapter`：[quantagent_platform.sec_plugins](sec_plugins.py)。
- `sec-adapter`：[quantagent_platform.sec_client](sec_client.py)。
- `sec-source-identities`：[quantagent_platform.sec_source_identities](sec_source_identities.py)，固定 SEC URL 与证据文件名。
- `p5-ports`：[quantagent_platform.p5_ports](p5_ports.py)，证据对象、错误、校验规则与存储接口。
- `p5-storage`：[quantagent_platform.p5_registry](p5_registry.py)。
- `p5-storage`：[quantagent_platform.p5_ledger](p5_ledger.py)。
- `p5-storage`：[quantagent_platform.p5_storage_services](p5_storage_services.py)，安全读取、目录、控制器锁和原子写入。
- `p5-composition`：[quantagent_platform.p5_bootstrap](p5_bootstrap.py)，启动时注入存储实现。
- `p5-domain`：[quantagent_platform.p5_handoff](p5_handoff.py)。
- `p5-domain`：[quantagent_platform.p5_review](p5_review.py)。
- `p5-adapter`：[quantagent_platform.p5_plugins](p5_plugins.py)。
- `runner`：[quantagent_platform.runner](runner.py)。
- `default-composition`：[quantagent_platform.bootstrap](bootstrap.py)，创建默认插件注册表。
- `agent-runtime`：[quantagent_platform.agents](agents.py)。
- `agent-runtime`：[quantagent_platform.manifests](manifests.py)。
- `p5-workflow`：[quantagent_platform.p5_coordinator](p5_coordinator.py)。
- `p5-workflow`：[quantagent_platform.p5_worker](p5_worker.py)。
- `http-api`：[quantagent_platform.result_api](result_api.py)。
- `http-api`：[quantagent_platform.submission_api](submission_api.py)。
- `http-api`：[quantagent_platform.task_lifecycle_api](task_lifecycle_api.py)。
- `http-api`：[api_storage](api_storage.py) / [api_requests](api_requests.py)，结果读取与操作员样本准入。
- `api-contracts`：[api_contracts](api_contracts.py)，共享 HTTP 模型、错误、配置与样本引用。
- `api-factory-port`：[api_ports](api_ports.py)，应用工厂的启动注入接口。
- `api-composition`：[api_bootstrap](api_bootstrap.py)，安装三个 API 的路由与生命周期。
- `cli-composition`：[quantagent_platform.cli](cli.py)。
- `startup`：[quantagent_platform.__main__](__main__.py)。
- `compatibility-exports`：[quantagent_platform](__init__.py)。

## 对外接口

旧 Monitor/Daily 通过 [legacy_workflows.py](legacy_workflows.py)执行顺序，[legacy_ports.py](legacy_ports.py)只定义显式回调及审计绑定；[legacy_bootstrap.py](legacy_bootstrap.py)绑定惰性审计工厂，消费时返回原类/质检函数，不构造存储或连接 SQLite。入口兼容及数据权限见[旧引擎说明](../docs/architecture/legacy-engine/README.md)。

通过已登记的公开模块或版本化配置使用；输入、输出、错误和副作用见项目既有契约。调用者不能访问其他能力的私有成员。

`RecipeRunner(registry)` 使用显式注册表；原 `RecipeRunner()`、`AgentRuntime()` 和 `default_registry()` 由包入口安装的工厂提供默认值，每次创建独立注册表。`bootstrap.build_default_registry()` 保留原目录校验；`install_default_registry()` 仅注入工厂，导入时不读取目录、不构造插件。自定义启动可通过 `runner.configure_default_registry(factory)` 注入，显式注册表优先。

原子状态写入仍先写完整临时 JSON 再替换；Windows 遇到替换错误 5/32 时最多尝试 5 次，间隔 10/20/30/40 ms。永久拒绝仍抛原异常并保留旧目标字节；其他错误和非 Windows 行为保持。真实读句柄与并发 HTTP 验证见 [D004 Task 2](../docs/features/d004-sec-contracts.md)。

Qlib/bt 的原无参插件通过 worker ports 调用 `read_bounded()`、`execute_json_worker()`；`worker_bootstrap.install_worker_services()` 只绑定无参 `LocalWorkerServices` 工厂，消费时创建无状态服务，原 IO 函数保持。自定义启动用 `configure_worker_services(factory)` 绑定，`get_worker_services_factory()` 可读取公开绑定；非法工厂抛 TypeError 且保留旧绑定，未绑定抛 RuntimeError。配置仅限可信启动阶段，不用于运行中切换账户或热替换。原 `isolated_runtime.WorkerExecution` 保留同一类型别名和 frozen 字段，旧 IO 函数签名仍可用；不承诺跨版本 pickle。

`P5Coordinator(..., services=...)` 可注入所属存储接口；默认由包入口安装 `LocalP5Services`，启动只绑定实现，不创建目录或打开数据库。创建协调器仍准备运行根及账本，执行仍写入原研究、交接与审计文件。`RoutePolicy.from_bytes(raw)` 校验有界策略；`load(path)`、`create_handoff(...)`、`verify_handoff(...)` 接受可选存储接口，校验失败继续抛 `HandoffError`。原 `p5_registry.ApprovedRun/SecEvidence/ApprovedSourceError/strict_json`、`p5_ledger.LedgerError` 和 `sec_client.SEC_URLS` 导入路径保留，实际类型归所属契约。自定义全局注入仅在可信启动阶段完成；不用于跨账户切换或运行中热替换，也不承诺旧 Python pickle 的跨版本恢复。

原 `result_api.create_app(config, submission=None)` 委托已注入的应用工厂；默认 `api_bootstrap.build_api_app()` 按原顺序安装结果、提交和任务路由。包入口只绑定工厂，核心导入不加载可选 HTTP 依赖、创建应用、目录或 worker。共享模型、错误、`ApiConfig` 和 `RegisteredFixture` 的原导入路径保留别名；`SubmissionConfig` 仍执行原样本白名单、大小和哈希校验。自定义工厂通过 `api_ports.configure_api_app_factory()` 在可信启动阶段绑定，不用于运行中切换账户。

`ResultStore.load_state(run_id, requester_subject)` 保留原授权校验；`summary_from_state()` 只格式化可信内部调用者已获授权的状态，不新增原始状态 HTTP 接口。`api_storage.read_bounded()`、`api_requests.decode_fixture()` / `parse_submission_request()` 保留原读取上限与错误语义。

`SecResponse` 保留六项位置参数及不可变、不展开响应正文的原语义，实际类型归 `sec_response_contracts`；原 `sec_client` / `sec_contracts` 类型与常量、`sec_source_identities.SEC_URLS` 继续导出同一对象。`normalize_sample()` 保留严格 JSON、来源、时间、哈希和大小校验；DTO 本身不执行准入或网络读取。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。运行器只引用 Packet 与插件 ports，具体插件归 bootstrap；兼容包入口初始化工厂，业务不能反向引用包根。剩余豁免以 [精确基线](../docs/architecture/legacy-baseline.json) 为准，新增违规立即失败。

P5 校验及工作流引用 ports，具体 IO 实现归 p5-storage；原文件链接、大小、替换与哈希检查保留。P5 ports 只引用 Packet，SEC 身份常量无业务或 SDK 引用。进程启动沿用包入口组装默认实现；显式协调器接口用于本进程，不替换 worker 的子进程实现。

三个 API 不互相导入，组装归 api-composition；请求准入和存储仍归 http-api，跨文件使用其公开接口。共享 API 契约无 IO 或工作流引用；组装器的函数内导入仍计入静态门禁。

SEC 标准化直接引用纯响应契约，不再引用具体客户端；纯响应文件只依赖标准库 dataclass。既有启动组装仍可导入具体插件和客户端，独立契约检查与整个包启动的检查分别记录。

信号、质检和报告版本标识归纯 `signal-report-contracts`；质检、日报、历史评价、Qlib 和 bt 直接引用该契约。原 `builtin_plugins` 常量导入保留别名，不改输出版本或权限。

Qlib/bt 不直接导入隔离运行适配器；worker ports 仅引用标准库及原 plugin-ports，具体 IO 仍归 isolated-runtime，由已登记组装器注入。输入、worker 路径和权限预检、日志/响应上限、超时和最小环境保持原控制。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

[D001 验收](../docs/features/d001-runner-composition.md) 核对原 Python 导出、目录、配方、预检和审计；新增兼容测试见 [test_runner_composition.py](../tests/integration/test_runner_composition.py)。

[D002 验收](../docs/features/d002-p5-boundaries.md) 核对 P5 边界、固定合成回证与原账本语义；测试入口见 [P5 集成](../tests/integration/p5/README.md)。

[D003 验收](../docs/features/d003-api-composition.md) 比较重构前 HTTP schema、响应、错误与缓存头，覆盖可选依赖、工厂注入、存储授权和关闭行为；入口见 [API 组装测试](../tests/integration/test_api_composition.py)。

[D004 验收](../docs/features/d004-sec-contracts.md) 核对旧类型身份、原 Packet、共享上限及无客户端的契约导入；原 SEC、P5 和完整离线回归保持。

[D005 验收](../docs/features/d005-adapter-contracts.md) 核对原版本标识、worker 类型/签名、惰性注入、默认配方与原实现；边界和公开服务接口覆盖在架构与契约测试。

## 已知限制

存量及治理状态统一见[架构规范](../docs/ARCHITECTURE.md)。门禁不是业务语义正确、跨账户隔离或生产可用性的证明；原 IO 职责未整体迁移。不得将离线样本结果称为真实收益或自动交易能力。
