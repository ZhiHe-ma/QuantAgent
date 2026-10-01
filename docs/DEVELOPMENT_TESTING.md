# 开发与测试文件归属

本仓库采用按业务能力划分的模块化单体，遵守 [架构规范](ARCHITECTURE.md)。先明确归属，再随具体整改迁移；当前仍部分符合，不建立空的目标目录。

| 文件类别 | 当前位置与归属 | 维护规则 |
| --- | --- | --- |
| 产品代码 | `quantagent_platform/`、`agent_engine.py`、`signal_audit.py` | 能力、公开入口和依赖由 [components.json](architecture/components.json) 登记；本批不移动 |
| 稳定契约与配置 | 同包中的 contracts；`schemas/`、`recipes/`、`policies/`、`plugins/`、`Agents/`、`Skills/` | 归属契约或对应能力；正式配置不能被测试辅助代码替代 |
| 开发工具 | `tools/architecture/` | 服务开发检查，保持独立；禁止通过检查导入执行业务模块 |
| 自动测试 | [tests/README.md](../tests/README.md) | unit 测模块规则；contract 测公开输入输出；integration 测跨组件；architecture 测源码与文档边界 |
| 测试支持 | 试点建立 `tests/support/`，含路径、SEC 合成构造器和 fakes | 支持模块不能导入测试用例；fake worker 是可执行替身，不是静态样本 |
| 固定样本 | `tests/fixtures/` | 保持 JSON/CSV/TXT 原字节、字符编码、来源和哈希；不装入私人账号数据 |
| 功能历史 | [docs/features/](features/README.md) | 记录完整源分支、变更、README 理由与验收；不覆盖模块当前有效说明 |
| 验收产物 | 忽略的 `artifacts/architecture/file-classification/` | 记录命令、环境、提交、结果与未测范围；公开说明只引用可发布结论 |
| 私人数据及现场脚本 | 仓库外各自的私有留存区 | OpenStock 拥有档案、规则、决定、回证；QuantAgent 管理公共证据与研究产物，禁止绕过所属模块更新 |
| 依赖环境及缓存 | `.venv/`、外部隔离环境与缓存 | 保持既有工作树位置与环境，不能作为源码或静态网页公开 |

## 本批目录与阅读顺序

先读本说明和 [架构规范](ARCHITECTURE.md)，再读 [设计](superpowers/specs/2026-10-02-file-classification-design.md)、[实施计划](superpowers/plans/2026-10-02-file-classification.md) 和 [分支说明](features/file-classification.md)。测试目录的当前文件链接以其 README 为准；仅试点迁移六个文件。

## 开发、测试与人工审查

先写功能分支说明、审查边界，再实现与测试，最后同步 README 和验收证据。README 随接口、行为、依赖或权限变化更新；无需更新时按能力逐项写明理由。自动门禁检查引用、登记和必填内容；人工审查职责是否合理、说明是否真实、私有数据是否仍由所属模块写入。

主测试命令为 `python -m unittest discover -s tests -v`；架构门禁为 `python -m tools.architecture --base-ref <目标提交> --branch <实际源分支>`。使用仓库外 Python，避免 Qlib 负向权限用例误把解释器纳入允许仓库目录。

## 学习与后续整改

未来学习只能提出候选经验与更新建议，按既定用户确认由数据所属模块更新；原始决定和当时理由保留，更正追加记录。学习闭环不允许源码依赖形成环。

本批不执行 D001–D006 业务重构，不上线 TypeScript 门禁，不调整仓库或环境位置。42 条精确登记问题须继续逐批清零；当前离线验收不能推断 CI、部署或生产可用性。
