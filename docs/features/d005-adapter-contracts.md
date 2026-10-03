# D005：适配器共享契约与运行接口 Implementation Plan

> For agentic workers: use superpowers:executing-plans inline, task by task; one independent whole-branch review at the end.

```json
{
  "branch": "refactor/d005-adapter-contracts",
  "base_commit": "d86787bc396ddbbfa9d0dd77f5269284e3d33d7e",
  "components": ["quality-adapter", "daily-adapter", "outcome-adapter", "qlib-adapter", "bt-adapter", "signal-report-contracts", "worker-ports", "worker-composition", "isolated-runtime", "compatibility-exports", "architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "只登记实际新增契约及组装能力，并删除已消除引用；检查器、规则和 CI 命令不变。"
  }
}
```

## 目标与非目标

Goal: 清除[整改清单](../architecture/remediation.md) D005 的六条精确引用，保留已验收输出和权限。

Spec: [架构规范](../ARCHITECTURE.md)、[文件与文档归属](../DEVELOPMENT_TESTING.md)。Architecture: 信号、质检和报告版本标识归 `signal_report_contracts.py`；Qlib/bt 通过 `worker_ports.py` 调用启动注入的原隔离运行实现，`worker_bootstrap.py` 负责绑定。Tech Stack: Python 3.12、unittest、现有 Import Linter；无新增依赖。

Global Constraints: 不改旧模块所属方、层级、原能力两两允许关系、门禁规则或扫描范围；豁免只能减少。保留 Python 正式导出、CLI/HTTP、固定配方、版本、权限、请求/响应及审计；不整改 D006，不实现学习或真实后端升级。原用户项目方案删除不纳入提交。本地、CI、部署与生产分开记录。

## 涉及模块

Task 1 修改五个适配器的版本标识引用。Task 2 修改 `qlib_plugins.py`、`bt_plugins.py`、`isolated_runtime.py` 和兼容启动包入口；原 worker 文件、默认目录及配方不变。新增文件分别登记实际职责，不创建空目录；所属 README 共用平台导航。

## 接口或数据变化

旧 `builtin_plugins.SIGNAL_CONTRACT/QUALITY_CONTRACT/REPORT_CONTRACT` 保留别名。原 `isolated_runtime.WorkerExecution(response, returncode, stdout_sha256, stderr_sha256)` 保留别名与 frozen 行为；`read_bounded(path, max_bytes, label)`、`execute_json_worker(context, *, display_name, file_prefix, python_executable, worker_path, request, timeout_seconds, max_response_bytes=2097152, max_log_bytes=65536)` 原实现和签名保持。

新 `WorkerServices` 定义上述两个方法，`configure_worker_services(factory)` 只在可信启动绑定无参工厂，公开转发函数保持原插件调用形式；默认 `LocalWorkerServices` 调用原 IO 实现。绑定不构造服务、不读取文件、不启动进程；无参插件和原默认注册表继续可用。DTO 模块元数据迁移，跨版本 pickle 和偶然私有导出不另作承诺。

## 新增依赖

新增纯版本标识只用标准库；worker ports 只依赖标准库与原 plugin-ports。新组装器依赖 ports 与原 isolated-runtime，由兼容启动入口调用；旧能力只添加指向新能力的允许项。不重新标记实际 IO 为 contracts，不添加旧能力之间的允许关系或新豁免。

## 测试证据

环境：2026-10-03，Windows、仓库外 Python 3.12.8、原 `.venv/Lib/site-packages`；命令从仓库根执行，UTF-8 输出。原始证据保存在忽略的 `artifacts/architecture/d005-adapter-contracts/`。实际解释器 `C:\Users\yj\AppData\Local\Programs\Python\Python312\python.exe`，`PYTHONPATH=<仓库>/.venv/Lib/site-packages`，门禁 PATH 包含 `D:\Git\cmd`。

Task 1（源码提交 `e4ccd9af4b4f84c99c27940bb41379364333c0e9`）：原回归 38 项、0 失败、2 项真实后端跳过，0.608 秒；新边界 RED 为 5 次预期断言失败，GREEN 加原回归 40 项、0 失败、2 跳过，0.609 秒。完整离线 `python -m unittest discover -s tests -v`：325 项、0 失败、7 环境跳过，68.570 秒；7 项为真实 bt/Qlib、私有 P4、三项 Windows 链接及临时卷未启用 8.3 文件名。该步门禁通过，54 模块、5 条存量、无循环，Import Linter 返回 0。

Task 2：`python -m unittest tests.architecture.test_adapter_boundaries tests.contract.test_worker_ports tests.test_platform tests.test_daily_plugins tests.test_outcome_replay tests.test_qlib_plugins tests.test_bt_plugins -v`：47 项、0 失败、2 跳过，1.662 秒。新测试初始 RED 有 9 次预期断言失败；恢复原两条运行器引用后，独立进程/静态检查再次失败，恢复新导入后 9/9 通过，1.780 秒。最终完整离线命令：332 项、0 失败、原 7 项环境跳过，69.222 秒。门禁通过，56 模块、3 条仅属 D006 的精确存量、无循环，Import Linter 返回 0；没有新增豁免。

`python artifacts/architecture/d005-adapter-contracts/verify_compatibility.py` 实际核对 174 个原资产、28 项原定义、2,500 组原允许关系、原常量及正式导出；原插件和 worker 方法体保持。两步原始日志均保留，验收版本在提交后补录；独立审查尚未运行。

### Task 1: 稳定信号与报告版本归属

Files: 新增 `quantagent_platform/signal_report_contracts.py`、`tests/architecture/test_adapter_boundaries.py`；修改 `builtin_plugins.py`、`daily_plugins.py`、`outcome_plugins.py`、`qlib_plugins.py`、`bt_plugins.py`、能力登记、精确基线和所属 README。

Interfaces: Produces 原三个字符串版本标识的唯一共享定义；Task 2 继续使用它们，不改值或旧入口。

- [x] 捕获原产品定义、固定资产哈希、原登记关系及包正式导出；执行 `python -m unittest tests.test_platform tests.test_daily_plugins tests.test_outcome_replay tests.test_qlib_plugins tests.test_bt_plugins -v`。Expected: 原离线用例通过，真实 Qlib/bt 按原开关跳过。
- [x] 新增静态测试 `test_adapters_do_not_import_quality_adapter`、`test_signal_report_contract_has_no_io_or_local_dependencies`。Expected: 四个原跨适配器引用及缺失纯契约按断言失败；检查不执行业务或联网。
- [x] 机械移动原三项常量定义，五个适配器改用新公开契约；保留旧常量别名及所有原函数体。Expected: 新边界和原消费用例通过。
- [x] 登记新能力并仅移除四条实际消除的 `→builtin_plugins` 基线，更新 README。执行上述原回归及 `python -m unittest tests.architecture.test_adapter_boundaries -v`。Expected: 四条引用消失，原 Packet、报告、质检、日报、历史评价和 worker 行为保持。
- [x] 执行 `python -m unittest discover -s tests -v` 及完整门禁 `python -m tools.architecture --base-ref d86787bc396ddbbfa9d0dd77f5269284e3d33d7e --branch refactor/d005-adapter-contracts --report artifacts/architecture/d005-adapter-contracts/gate.json`，单独提交。Expected: 完整离线回归无失败、存量 9→5、无循环、Import Linter 返回 0。

### Task 2: 隔离 worker 的公开 ports 与启动注入

Files: 新增 `quantagent_platform/worker_ports.py`、`quantagent_platform/worker_bootstrap.py`、`tests/contract/test_worker_ports.py`；修改两个插件、`isolated_runtime.py`、`__init__.py`、边界测试、登记、精确基线和所属 README。

Interfaces: Consumes Task 1 原报告契约；Produces `WorkerExecution`、`WorkerServices`、上述两项公开转发函数及 `configure_worker_services(factory)`、`get_worker_services_factory() -> Callable[[], WorkerServices]`。`worker_bootstrap.install_worker_services()` 绑定无参 `LocalWorkerServices` 工厂。

- [x] 新增 `test_worker_adapters_use_ports_and_contracts_have_no_io`；契约测试覆盖注入后有界读取及完整关键字参数转发、错误传播、原 frozen 类型别名和原默认注册表的真实 fake-worker 配方。Expected: 缺失 ports/组装和原直接运行器引用按断言失败；不以缺失测试导入报错代替 RED。
- [x] 移动原 DTO，添加纯接口和启动工厂；原运行函数不改，只增加无状态服务实现与启动绑定。两个插件仅改导入，不改方法体或构造形式。Expected: 新契约测试及原 fake-worker 回归通过。
- [x] 验证服务未绑定或非法工厂明确失败；既有包启动后单独重载 ports/插件不直接依赖运行器。保持原 10 MiB 输入、2 MiB 响应、64 KiB 日志、超时、哈希、错误和最小环境；全量回归涵盖原权限预检及 CLI/HTTP。
- [x] 登记两个新能力并删除仅剩的两条 D005 基线，更新所属 README/整改状态。运行 `python -m unittest discover -s tests -v` 和上述完整门禁。Expected: 全部原离线断言继续通过；跳过逐项记录；剩余 3 条仅属 D006，无循环或新增违规。
- [ ] 单独提交源码/测试，记录实际验收 SHA；一次独立只读审查整个分支，归档本批执行记录，保留本地分支和工作树。

Review Focus: 旧版本标识和真实消费结果；原 WorkerExecution 类型身份/不可变字段及公开函数参数；启动仅绑定、无参插件与显式自定义工厂并存；输入/日志/响应大小、超时、哈希和环境隔离错误语义；原 Python 导出、CLI/HTTP、目录配方与权限审计；旧登记允许关系不扩张，IO 实现仍归实际适配器。

## 回滚方式

回退本批本地提交恢复原引用、登记及精确基线。没有数据迁移，不改写旧研究、报告、数据库或运行目录；原用户删除保持。

## 遗留问题

当前仍部分符合，D006 继续按精确基线整改。真实 SEC、私有 P4、真实 Qlib/bt、Linux/远端 CI、部署和生产未运行；离线 worker 替身只验证宿主协议，不验证第三方研究或回测引擎。单独重载检查区分契约依赖和既有启动组装，不声称整个包从不导入具体执行代码。
