# 版本化 JSON Schema

## 职责与边界

约束公开请求、Agent/Skill 声明、交接、研究与运行结果的 JSON 形状。Schema 提供版本化格式，不负责业务编排、存储连接或权限授予；业务有效性还需所属模块校验。

## 文件导航

- [quantagent.agent_handoff.v1.schema.json](quantagent.agent_handoff.v1.schema.json)
- [quantagent.agent_manifest.v1.schema.json](quantagent.agent_manifest.v1.schema.json)
- [quantagent.agent_manifest.v2.schema.json](quantagent.agent_manifest.v2.schema.json)
- [quantagent.evidence_bundle.v1.schema.json](quantagent.evidence_bundle.v1.schema.json)
- [quantagent.read_api.run_summary.v1.schema.json](quantagent.read_api.run_summary.v1.schema.json)
- [quantagent.research_request.v1.schema.json](quantagent.research_request.v1.schema.json)
- [quantagent.run_status.v2.schema.json](quantagent.run_status.v2.schema.json)
- [quantagent.sec_approved_run.v1.schema.json](quantagent.sec_approved_run.v1.schema.json)
- [quantagent.skill_manifest.v1.schema.json](quantagent.skill_manifest.v1.schema.json)
- [quantagent.submit_run.v1.schema.json](quantagent.submit_run.v1.schema.json)
- [quantagent.thesis_state.v1.schema.json](quantagent.thesis_state.v1.schema.json)

## 对外接口

调用方按具体契约版本选取 schema，使用 Draft 2020-12 校验必填字段、类型、枚举及结构。失败由所属模块转换为契约或请求错误；校验本身不写业务数据。字段变化必须说明兼容策略，不能用同名版本悄悄改变公开含义。

## 依赖规则

允许依赖由 [components.json](../docs/architecture/components.json) 精确登记；规则见 [架构规范](../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

## 数据与权限

QuantAgent 仅管理公共证据、研究结果与本机授权的审计产物；运行目录与文件权限沿用原有控制。私有档案、规则、决定和回证由 OpenStock 管理，不得跨账户读取或直接写入。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

当前部分符合。存量循环和混合职责尚未整改；门禁不是业务语义正确、跨账户隔离或生产可用性的证明。不得将离线样本结果称为真实收益或自动交易能力。
