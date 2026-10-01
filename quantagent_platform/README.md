# 插件平台与现有功能导航

## 职责与边界

插件平台与现有功能导航。本目录只承担登记能力，具体业务接口以原有契约文档为准；不取得其他模块的数据写权限。

## 文件导航

- `packet-contracts`：[quantagent_platform.contracts](contracts.py)。
- `research-contracts`：[quantagent_platform.research_contracts](research_contracts.py)。
- `sec-contracts`：[quantagent_platform.sec_contracts](sec_contracts.py)。
- `plugin-ports`：[quantagent_platform.plugins](plugins.py)。
- `daily-domain`：[quantagent_platform.daily_workflow](daily_workflow.py)。
- `sec-domain`：[quantagent_platform.sec_analysis](sec_analysis.py)。
- `quality-adapter`：[quantagent_platform.builtin_plugins](builtin_plugins.py)。
- `daily-adapter`：[quantagent_platform.daily_plugins](daily_plugins.py)。
- `outcome-adapter`：[quantagent_platform.outcome_plugins](outcome_plugins.py)。
- `thesis-adapter`：[quantagent_platform.research_plugins](research_plugins.py)。
- `isolated-runtime`：[quantagent_platform.isolated_runtime](isolated_runtime.py)。
- `qlib-adapter`：[quantagent_platform.qlib_plugins](qlib_plugins.py)。
- `qlib-adapter`：[quantagent_platform.qlib_worker](qlib_worker.py)。
- `bt-adapter`：[quantagent_platform.bt_plugins](bt_plugins.py)。
- `bt-adapter`：[quantagent_platform.bt_worker](bt_worker.py)。
- `sec-adapter`：[quantagent_platform.sec_plugins](sec_plugins.py)。
- `sec-adapter`：[quantagent_platform.sec_client](sec_client.py)。
- `p5-storage`：[quantagent_platform.p5_registry](p5_registry.py)。
- `p5-storage`：[quantagent_platform.p5_ledger](p5_ledger.py)。
- `p5-domain`：[quantagent_platform.p5_handoff](p5_handoff.py)。
- `p5-domain`：[quantagent_platform.p5_review](p5_review.py)。
- `p5-adapter`：[quantagent_platform.p5_plugins](p5_plugins.py)。
- `runner`：[quantagent_platform.runner](runner.py)。
- `agent-runtime`：[quantagent_platform.agents](agents.py)。
- `agent-runtime`：[quantagent_platform.manifests](manifests.py)。
- `p5-workflow`：[quantagent_platform.p5_coordinator](p5_coordinator.py)。
- `p5-workflow`：[quantagent_platform.p5_worker](p5_worker.py)。
- `http-api`：[quantagent_platform.result_api](result_api.py)。
- `http-api`：[quantagent_platform.submission_api](submission_api.py)。
- `http-api`：[quantagent_platform.task_lifecycle_api](task_lifecycle_api.py)。
- `cli-composition`：[quantagent_platform.cli](cli.py)。
- `startup`：[quantagent_platform.__main__](__main__.py)。
- `compatibility-exports`：[quantagent_platform](__init__.py)。

## 对外接口

通过已登记的公开模块或版本化配置使用；输入、输出、错误和副作用见项目既有契约。调用者不能访问其他能力的私有成员。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
