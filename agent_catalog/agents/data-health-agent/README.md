# builtin.data-health-research-agent

## 职责与边界

版本 1.0.0 的确定性 Agent 声明，绑定 Skill builtin.signal-data-health@1.0.0 与配方 historical-data-health@1.0.0。声明能力范围，不自行执行 Python、扩大路由或取得交易权限。

## 文件导航

先读 [agent.yaml](agent.yaml)，再读 [目录清单](../../catalog.json) 及 [Agent 导航](../README.md)；执行入口为仓库 AgentRunner。

## 对外接口

输入 `quantagent.research_request.v1`，输出 `quantagent.report.v1`；能力集合为 source.signal_history, quality.signal_history, report.data_quality。AgentRunner 预检精确版本、哈希、插件绑定、权限与预算，失败时拒绝执行；模型 allowed_models 为空。

## 依赖规则

只通过声明引用锁定 Skill/Recipe；依赖规则见 [有效架构](../../../docs/ARCHITECTURE.md)。不得动态改清单或读取其他模块内部变量。

## 数据与权限

声明本身不保存业务数据。报告和运行审计归 QuantAgent 公共研究域；私有档案、用户决定和回证归 OpenStock。文件读写由具体插件权限和执行根控制。

## 测试与验收

`python -m unittest discover -s tests -p test_agent_runtime.py -v` 验证预检；SEC 角色另由 test_p5_agents.py/test_p5_manifest.py 固定样本覆盖。完整验收及未测项见 [本批说明](../../../docs/features/architecture-guardrails.md)。

## 已知限制

当前声明和固定样本通过不等于真实模型、后端或生产验收。清单 verified 状态不授权自动交易或自动改规则。
