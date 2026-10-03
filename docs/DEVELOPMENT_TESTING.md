# 文件与文档归属

采用按业务能力划分的模块化单体，边界见[架构规范](ARCHITECTURE.md)。现有平铺文件先登记归属，再随对应整改迁移。

## 文件分类

| 类别 | 位置与维护要求 |
| --- | --- |
| 产品代码 | `quantagent_platform/`、`agent_engine.py`、`signal_audit.py`；范围和入口按[能力登记](architecture/components.json)维护 |
| 契约与配置 | `schemas/`、`recipes/`、`policies/`、`plugin_catalog/`、`agent_catalog/`及所属 contracts；正式配置不能被测试替身替代 |
| 开发工具 | `tools/architecture/`；静态读取产品代码，禁止导入执行或联网 |
| 自动测试 | [tests](../tests/README.md)：unit 验证模块规则，contract 验证公开接口，integration 验证跨组件，architecture 验证边界 |
| 测试支持 | `tests/support/`含路径、构造器和 fake worker；不导入测试用例，不成为产品共享库 |
| 固定样本 | `tests/fixtures/`；保留 JSON/CSV/TXT 字节、编码、来源与哈希，不放私人账户数据 |
| 验收产物 | 忽略的 `artifacts/`；原始日志留本地，公开文档记录可发布结论 |
| 私人资料 | 仓库外受控目录；归属与写入边界见架构规范 |
| 环境和缓存 | `.venv/`及各自隔离环境、缓存；不作为源码或静态网页发布 |

## 文档各写什么

| 文档 | 唯一维护的内容 |
| --- | --- |
| 项目 README | 项目定位、最短使用入口、阅读导航 |
| [USAGE.md](USAGE.md) | 完整命令、运行配置及使用边界；中文、英文 README 共用 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 共同依赖规则、数据归属与合并要求 |
| 本文 | 文件分类和文档维护方式 |
| 功能 README | 本功能当前职责、入口、接口和限制；共同规则使用链接 |
| [分支说明](features/README.md) | 本次目标、变更、验收与回滚，合并后作为历史保留 |
| `docs/superpowers/specs/`、`plans/`及验收记录 | 当时的设计、执行安排和结果；不能当作已实现功能或最新状态 |

功能 README 保留七项：**职责与边界、文件导航、对外接口、依赖规则、数据与权限、测试与验收、已知限制**。每项只写本功能需要的信息；接口说明涵盖输入、输出、错误与副作用，依赖和权限说明链接共同规则并列出本功能差异。

## 维护顺序

先写分支说明 → 审查边界 → 实现与验证 → 同步所属 README 和验收证据。接口、行为、依赖或权限改变时更新 README；无需更新则按受影响能力逐项说明理由。

同一规则只在所属文档修改，其他位置链接引用。发现冲突时核对源码与证据，修正当前说明；历史设计、计划和验收保留当时范围、版本与日期。测试命令见[测试导航](../tests/README.md)，门禁细节见[工具说明](../tools/architecture/README.md)。

## 按需读取

先按[能力登记](architecture/components.json)确定本次范围，用 `python -m tools.architecture --context-for <能力ID>` 生成清单；多能力重复选项。基础读取为 AGENTS、ARCHITECTURE、本文，再加受影响能力 README；同一实际文件去重。当前分支说明定位目标、当前任务和验收结论，历史设计、长篇手册及完整日志按引用查阅。

[预算政策](architecture/documentation-budget.json)约束当前入口／规范／登记 README 的篇幅及能力默认阅读量，超限须缩短当前说明、链接所属详细资料或拆分任务；保留完整证据及必需规则。计量为规范化文本行数与字符数，不代表模型真实 token 或整段对话用量。当前政策的范围及命令详见工具说明。

长任务在当前分支说明保留简短进度，记录已完成、当前提交、下一步和未测范围；原始日志留本地。上下文重建先定位进度和当前任务，不反复整份读取历史计划，也不新增重复的规则文档。
