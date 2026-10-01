# thesis-tracker 功能说明

## 职责与边界

围绕 source.thesis_review, research.thesis_update, report.thesis 提供声明和使用步骤。由目录清单锁定版本和哈希，经 Agent/Recipe 权限预检调用；详见 SKILL.md，不自行扩大权限、改路由或取得私人数据。

## 文件导航

- [NOTICE.md](NOTICE.md)
- [SKILL.md](SKILL.md)
- [skill.yaml](skill.yaml)

## 对外接口

Skill `anthropic-financial-services-adapted.thesis-tracker@1.0.0` 声明输入 `quantagent.research_request.v1`, `quantagent.evidence_bundle.v1`, `quantagent.thesis_state.v1`, `quantagent.thesis_review_input.v1`，输出 `quantagent.thesis_state.v1`, `quantagent.report.v1`；由兼容配方调用。内容文件及 package_sha256 在 skill.yaml 锁定，哈希或能力不匹配会被现有预检拒绝。说明文字本身不执行工具；实际副作用取决于授权插件。

## 依赖规则

允许依赖由 [components.json](../../../docs/architecture/components.json) 精确登记；规则见 [架构规范](../../../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
