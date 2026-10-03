# QuantAgent 开发约束

开始改动前按[读取规则](docs/DEVELOPMENT_TESTING.md#按需读取)核对预算清单，再读取[架构规范](docs/ARCHITECTURE.md)、[文件与文档归属](docs/DEVELOPMENT_TESTING.md)及受影响功能的 README。共同规则在这两份规范维护，本文件只列开发动作。

- 先写[分支说明](docs/features/README.md)，再审查边界、实现、验证和补齐证据；新代码必须登记所属能力。
- 接口、行为、依赖或权限变化时更新所属 README；无需更新则按能力说明理由。
- 用 `python -m tools.architecture --context-for <能力ID>` 生成阅读清单；多能力重复该选项。超限时定位职责拆分或按任务分段读取，保留完整原文和必需规则。
- 精确存量豁免随整改减少；不放宽依赖、扫描或数据权限来隐藏违规。
- 验证命令见[测试导航](tests/README.md)和[门禁工具](tools/architecture/README.md)。记录环境、提交、结果、跳过和未测范围，本地、CI、部署与生产分别填写。
- 人工核对职责、文档真实性、豁免理由及数据写入边界；未运行就明确写未运行。
- 不提交凭据、Cookie、私人资料或运行数据库；未经用户要求不合并或部署。
