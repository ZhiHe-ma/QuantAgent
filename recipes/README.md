# 受控配方

## 职责与边界

声明版本化步骤、能力、插件绑定和配置占位符，由 RecipeRunner 预检并执行。配方不拥有插件实现、模型选择权或账户资料；改变步骤契约须回归固定样本。

## 文件导航

- [bt_portfolio_backtest.json](bt_portfolio_backtest.json)
- [historical_data_health.json](historical_data_health.json)
- [offline_daily_research.json](offline_daily_research.json)
- [offline_outcome_backfill.json](offline_outcome_backfill.json)
- [qlib_factor_research.json](qlib_factor_research.json)
- [sec_evidence_producer.json](sec_evidence_producer.json)
- [sec_evidence_review.json](sec_evidence_review.json)
- [sec_industry_peers.json](sec_industry_peers.json)
- [thesis_tracker.json](thesis_tracker.json)

## 对外接口

JSON 使用 recipe_id、recipe_version、steps；步骤含 id、capability、plugin、config。调用方提供 source_path/report_title 等变量，预检核对契约和授权；运行产生 DataPacket、状态与报告。部分配方读本地文件、写报告或审计，Qlib/bt/SEC 配方另需对应后端或数据源；权限不满足时预检失败。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
