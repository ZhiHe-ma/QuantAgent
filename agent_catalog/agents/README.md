# agents 功能说明

## 职责与边界

保存各确定性 Agent 的版本化能力、Skill/Recipe、模型政策、预算和审核声明；由 AgentRunner 预检并执行。此目录不提供业务实现，也不决定任意多 Agent 路由。

## 文件导航

- [data-health-agent](data-health-agent/README.md)：`builtin.data-health-research-agent`。
- [research-agent](research-agent/README.md)：`builtin.research-agent`。
- [sec-evidence-producer-agent](sec-evidence-producer-agent/README.md)：`builtin.sec-evidence-producer-agent`。
- [sec-evidence-review-agent](sec-evidence-review-agent/README.md)：`builtin.sec-evidence-review-agent`。

## 对外接口

agent.yaml 按 Agent manifest v1/v2 Schema 验证，并由 catalog.json 锁定 ID/版本与 SHA256。调用方提交研究请求，AgentRunner 核对所有声明后运行对应配方；无效声明、越权能力或预算不匹配时拒绝运行。

## 依赖规则

允许依赖由 [components.json](../../docs/architecture/components.json) 精确登记；规则见 [架构规范](../../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
