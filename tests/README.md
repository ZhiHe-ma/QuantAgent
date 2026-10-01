# 离线验证与验收

## 职责与边界

离线验证与验收。本目录只承担登记能力，具体业务接口以原有契约文档为准；不取得其他模块的数据写权限。

## 文件导航

- [test_agent_runtime.py](test_agent_runtime.py)
- [test_bt_plugins.py](test_bt_plugins.py)
- [test_daily_plugins.py](test_daily_plugins.py)
- [test_dry_run.py](test_dry_run.py)
- [test_idempotency_error_isolation.py](test_idempotency_error_isolation.py)
- [test_manifest_spec.py](test_manifest_spec.py)
- [test_outcome_replay.py](test_outcome_replay.py)
- [test_p5_agents.py](test_p5_agents.py)
- [test_p5_cli_api.py](test_p5_cli_api.py)
- [test_p5_coordinator.py](test_p5_coordinator.py)
- [test_p5_handoff.py](test_p5_handoff.py)
- [test_p5_ledger.py](test_p5_ledger.py)
- [test_p5_live_acceptance.py](test_p5_live_acceptance.py)
- [test_p5_manifest.py](test_p5_manifest.py)
- [test_p5_registry.py](test_p5_registry.py)
- [test_p5_review.py](test_p5_review.py)
- [test_p5_worker.py](test_p5_worker.py)
- [test_platform.py](test_platform.py)
- [test_qlib_plugins.py](test_qlib_plugins.py)
- [test_result_api.py](test_result_api.py)
- [test_run_cancellation.py](test_run_cancellation.py)
- [test_schema.py](test_schema.py)
- [test_sec_analysis.py](test_sec_analysis.py)
- [test_sec_client.py](test_sec_client.py)
- [test_sec_contracts.py](test_sec_contracts.py)
- [test_sec_workflow.py](test_sec_workflow.py)
- [test_signal_audit.py](test_signal_audit.py)
- [test_signal_audit_integration.py](test_signal_audit_integration.py)
- [test_submission_api.py](test_submission_api.py)
- [test_task_lifecycle_api.py](test_task_lifecycle_api.py)
- [test_thesis_tracker.py](test_thesis_tracker.py)

## 对外接口

通过已登记的公开模块或版本化配置使用；输入、输出、错误和副作用见项目既有契约。调用者不能访问其他能力的私有成员。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

根命令 `python -m unittest discover -s tests -v` 会发现 architecture 子包；单独运行 `python -m unittest discover -s tests/architecture -v`。外部后端验收按既有环境开关运行，跳过项不代表已验收。Windows 本地 Python 应位于仓库外，避免 Qlib 负向用例的可执行路径落入允许仓库根目录。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
