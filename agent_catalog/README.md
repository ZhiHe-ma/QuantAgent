# Agent 与 Skill 精选目录

## 职责与边界

锁定 Agent、Skill、Recipe 的 ID、版本、验证状态、相对路径与 SHA256。只决定可用清单；权限预检和运行由 AgentRunner/RecipeRunner 负责，新增清单条目不自动授予执行权限。

## 文件导航

- [catalog.json](catalog.json)
- [agents/README.md](agents/README.md)：各 Agent 的声明。
- [skills/thesis-tracker/README.md](skills/thesis-tracker/README.md)：研究假设跟踪示例。

## 对外接口

AgentCatalog.load 读取 catalog.json；get 按精确 ID/版本返回验证后的声明。路径越界、重复标识、哈希或身份不一致触发 ManifestError；AgentRunner 继续核对 Agent、Skill、Recipe 的能力集合与执行预算。目录变更需同时核对清单锁定关系。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
