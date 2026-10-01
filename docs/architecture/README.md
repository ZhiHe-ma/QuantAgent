# 能力登记与存量整改

## 职责与边界

能力登记与存量整改。本目录只承担登记能力，具体业务接口以原有契约文档为准；不取得其他模块的数据写权限。

## 文件导航

- [components.json](components.json)
- [legacy-baseline.json](legacy-baseline.json)

## 对外接口

components.json version=1：每项能力包含 id、kind、modules、public_modules、allows、external_dependencies、readme、data_owner、assets。modules/依赖/豁免禁止通配；assets 中目录以 / 结尾，映射文档变更范围；directory_roots 发现 Agent/Skill 的独立子目录，必须单独登记并拥有 README。legacy-baseline.json 保存原始提交、具体规则/引用/成员、理由与整改任务。

## 依赖规则

允许依赖由 [components.json](components.json) 精确登记；规则见 [架构规范](../ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
