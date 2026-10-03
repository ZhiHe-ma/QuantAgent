# D006：旧引擎工作流与审计注入 Implementation Plan

> For agentic workers: use superpowers:executing-plans inline; one independent whole-branch review after verification.

```json
{
  "branch": "refactor/d006-legacy-workflows",
  "base_commit": "ae9024208a002d26fd533a1148a37736a52d9306",
  "tested_commit": "9f9ccd8d10e97f30a87bc9c531b22410a3063d27",
  "components": ["legacy-engine", "signal-audit", "daily-domain", "compatibility-exports", "legacy-ports", "legacy-workflows", "legacy-composition", "architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "检查器、扫描范围、依赖规则与 CI 命令不变；只登记真实新增能力和移除已消除的精确基线。"
  }
}
```

## 目标与非目标

Goal: 消除 D006 三项存量；保留旧 `QuantAgent`、CLI、Monitor/Daily 行为及审计结果。Spec: [架构规范](../ARCHITECTURE.md)、[文件与文档归属](../DEVELOPMENT_TESTING.md)及[整改项](../architecture/remediation.md#d006旧引擎)。Tech Stack: Python 3.12、unittest、原 Import Linter；无新依赖。

Architecture: `legacy_workflows.py` 负责两个流程的执行顺序，只通过 `legacy_ports.py` 的公开回调协作；入口仍提供原网络、模型及文件能力。`legacy_bootstrap.py` 惰性组装原审计实现；实际 SQLite 继续归 `signal_audit.py`。不迁移整个仓库，不实现学习、交易或新后端。

Global Constraints: 不改旧模块层级、归属、原能力两两允许关系、门禁规则、扫描或配置样本；只新增真实能力及相关引用。保留 dry-run、同日跳过/强制执行、消息确认、失败重试/隔离、日报/Memory/审计写入顺序和错误；不改原测试或 SQL。原用户项目方案删除不纳入提交；不推送、合并或部署。

## 涉及模块

新增 `quantagent_platform/legacy_ports.py`、`legacy_workflows.py`、`legacy_bootstrap.py`；修改 `agent_engine.py` 的两项流程入口和导入、`signal_audit.py` 的基础异常归属、兼容包启动、能力登记及精确基线。所属 README 共用现有功能导航，不创建空目录。

## 接口或数据变化

保留 `QuantAgent()` 和原公开方法签名。`run_monitor_pipeline`、`run_daily_pipeline` 委托显式 `MonitorPorts`/`DailyPorts`；工作流不读取入口内部变量、不自行文件/数据库/网络 IO。原审计类及质检函数通过 `LegacyAuditBindings` 启动工厂提供，旧入口所见类型/函数与原实现相同；`SignalAuditError` 移入稳定接口，原存储模块保留同一类型别名。错误类型模块元数据变化，不承诺跨版本 pickle。

## 新增依赖

新工作流仅引用所属 ports、原日报业务及标准库；新启动组装引用 ports 和原审计适配器。包启动只绑定工厂，消费时取得原类/函数，不构造存储、不连接数据库。旧能力只增加指向新能力的允许项，原能力之间的允许关系保持。

## 测试证据

环境：2026-10-03，Windows，Python 3.12.8；`PYTHONPATH=<仓库>;<仓库>/.venv/Lib/site-packages`、UTF-8；门禁 PATH 含 `D:\Git\cmd`。基准提交见首个 JSON；原始日志和不可变基线放在忽略的 `artifacts/architecture/d006-legacy-workflows/`。

原定向回归 38 项、0 失败，20.235 秒；初次命令误指不存在的 `tests.test_rss`，记录为 24 项通过及 1 项加载错误，已更正实际测试路径并重跑。不可变基线：162 原资产、34 原产品定义、53 原能力/2,809 组允许关系及正式导出。

新 8 项测试先 RED：三类旧违规和缺失能力触发 14 次预期断言失败，无测试导入错误。实现后的首轮新样本字段/表名不符原数据契约，修正新样本；临时数据库连接必须显式关闭，修正新测试清理。原测试与产品规则不变。最终定向命令 `python -m unittest tests.architecture.test_legacy_boundaries tests.contract.test_legacy_ports tests.test_dry_run tests.test_idempotency_error_isolation tests.test_signal_audit tests.integration.audit.test_signal_audit_integration -v`：46 项、0 失败、无跳过，1.442 秒。兼容核对通过；仅两项原流程迁移，其他原方法/资产/允许矩阵保持。

完整离线 `python -m unittest discover -s tests -v` 实际运行 **340 项、0 失败、7 项原环境跳过，70.446 秒**。跳过：真实 Qlib、真实 bt、私有 P4、三项 Windows 链接权限及临时卷未启用 8.3 文件名。完整架构/文档门禁通过：59 模块、0 存量、无循环或错误、Import Linter 返回 0。原所有测试、SQL、固定配方/样本、其他产品文件、原 2,809 组允许关系及正式导出保持。完整结果对应首个 JSON 的 `tested_commit`；后续仅补录文档，独立审查尚未运行。

### Task 1: 迁移执行顺序，注入原审计实现

Files: 上述三项新源码及 `tests/architecture/test_legacy_boundaries.py`、`tests/contract/test_legacy_ports.py`；原入口、存储、登记、基线和所属 README。

Interfaces: Produces `MonitorPorts`、`DailyPorts`、`LegacyAuditBindings`、`configure_legacy_audit_factory(factory)`、`get_legacy_audit_factory()`、`get_legacy_audit_bindings()`；公开工作流 `run_monitor_pipeline(ports)`、`run_daily_pipeline(ports)`；`install_legacy_audit_factory()` 仅绑定组装。Consumes 原日报函数、审计类及质检规则。

- [x] 捕获原资产、产品定义、正式导出和 53 项能力允许关系；执行 `python -m unittest tests.test_dry_run tests.test_idempotency_error_isolation tests.test_signal_audit tests.integration.audit.test_signal_audit_integration -v`。Expected: 原离线回归无失败；捕获不得覆盖。
- [x] 新静态测试拒绝旧两条越界/动态导入，并验证 ports 无 IO、工作流仅消费公开回调；新消费测试覆盖自定义审计绑定、惰性启动/错误、实际临时数据库和独立进程加载。Expected: 对缺失功能及三条原违规发生断言失败，不以测试导入错误替代 RED。
- [x] 机械迁移 Monitor/Daily 顺序到工作流；文件操作保留在入口回调，审计由可信惰性工厂注入，`argparse` 普通导入。Expected: 新测试和全部原引擎用例通过；原其余方法、存储方法、质检、SQL 与固定资产保持。
- [x] 登记三个真实能力，仅删除三条已消除基线；同步 README、整改清单和当前架构状态。执行原定向回归、新测试及 `python -m unittest discover -s tests -v`。Expected: 无失败；原环境跳过单列；真实 IO 仍归原模块。
- [ ] 执行 `python -m tools.architecture --base-ref ae9024208a002d26fd533a1148a37736a52d9306 --branch refactor/d006-legacy-workflows --report artifacts/architecture/d006-legacy-workflows/gate.json`；固定源码/测试提交，独立审查、验收记录与归档。Expected: 存量 3→0，无循环/新增违规/放宽规则；Import Linter 返回 0，保留本地分支及工作树。

Review Focus: 消息未确认、Memory/日报/审计失败时的真实副作用与顺序；Monitor 重试恢复/毒新闻隔离和 dry-run；原审计类型身份、默认路径、原始 source_sha256 与版本标识；入口按文件加载及 signal_audit 优先导入的初始化顺序；原 Python/CLI/HTTP、固定配方、权限及原允许矩阵兼容。

## 回滚方式

回退本批本地提交，恢复原两项流程及三条精确基线；无数据迁移，数据库和研究产物不改写，原用户删除保留。

## 遗留问题

真实模型、新闻、行情、消息、真实 Qlib/bt、SEC、私有 P4、Linux/远端 CI、部署及生产未运行；dry-run 仍可能访问网络和模型。存量清零的机器检查与人工职责审查分别记录，不以本地门禁推断生产验收。
