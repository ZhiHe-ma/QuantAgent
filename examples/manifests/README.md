# manifests 功能说明

## 职责与边界

manifests 功能说明。本目录只承担登记能力，具体业务接口以原有契约文档为准；不取得其他模块的数据写权限。

## 文件导航

- [research-agent.example.json](research-agent.example.json)
- [thesis-tracker.example.json](thesis-tracker.example.json)

## 对外接口

通过已登记的公开模块或版本化配置使用；输入、输出、错误和副作用见项目既有契约。调用者不能访问其他能力的私有成员。

## 依赖规则

允许依赖由 [components.json](../../docs/architecture/components.json) 精确登记；规则见 [架构规范](../../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。

## 原有使用说明

# Manifest examples

These files are structural P0 examples for Schema validation. They are deliberately marked `example_only` and are not installable Agent/Skill packages: the referenced Recipe, Skill files and recorded model are not present yet, and the Skill hashes are placeholders.

P1 must replace them with executable positive fixtures plus negative fixtures. P2 must generate hashes from the actual adapted `thesis-tracker` package and retain its upstream license and modification record.
