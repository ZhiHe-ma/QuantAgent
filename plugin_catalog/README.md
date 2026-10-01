# 插件精选目录

## 职责与边界

记录已知插件的精确版本、验证状态、来源和许可证说明。此清单是预检证据，插件 Python 实现与注册属于运行器/适配器；列入清单不表示所有真实后端已运行。

## 文件导航

- [catalog.json](catalog.json)

## 对外接口

catalog.json 以 catalog_version、plugins 提供 plugin_id/version/status/upstream/license/notes。RecipeRunner 对照所选插件和版本核验；执行输入输出由插件 ports 与 DataPacket 契约定义。该 JSON 自身不执行插件，不授予读写或联网权限。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
