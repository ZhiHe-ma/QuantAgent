# 受控运行策略

## 职责与边界

固定 P5 SEC producer→reviewer 路由、清单/声明哈希、权限与执行预算。路由由协调器执行，Agent/Skill 不能自行选择下游或扩大预算；首批只有既有 SEC 策略。

## 文件导航

- [p5_sec_route.v1.json](p5_sec_route.v1.json)

## 对外接口

p5_sec_route.v1.json 使用 policy_version、task_type、source_contract、parent、child、limits，绑定精确 Agent/Skill/Recipe/Plugin 和哈希；只容许深度 1、交接 1 次、120 秒、模型费用 0。协调器在预检发现不一致时失败，不接受任意新路由。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
