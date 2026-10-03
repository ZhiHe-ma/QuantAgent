# 文档篇幅与上下文阅读预算

```json
{
  "branch": "feature/doc-context-budgets",
  "base_commit": "3717263081ec079d0a38d2284919f329d312edef",
  "phase": "implemented",
  "components": ["architecture", "acceptance-tests"],
  "readme_unchanged": {}
}
```

## 目标与非目标

落实用户已要求执行的文档篇幅和上下文预算检查，增量扩展现有静态门禁；按能力生成去重阅读清单，帮助开发只读取当前任务相关文档。沿用当前隔离工作树，新建功能分支，保留原 R001 分支和用户文件删除。

预算是规范化文本的行数、Unicode 字符数，不是模型真实 token 数；不拦截工具读取或计算整段对话、代码、技能和模型提示词的总上下文。原历史方案、分支记录和验收日志保留完整，不自动截断或重写。

## 涉及模块

[文档门禁](../../tools/architecture/README.md)扩展检查和 CLI；[架构测试](../../tests/architecture/README.md)验证正反例。同步[维护规则](../DEVELOPMENT_TESTING.md)、开发约束与所属 README，不增加另一套 Markdown 规范。

## 接口或数据变化

- 新增 `docs/architecture/documentation-budget.json`：当前文档最多 160 行／9,000 字符，阅读清单最多 300 行／15,000 字符。当前 40 份入口／登记 README 的最长文档为 112 行／7,978 字符；限额包含有限增长空间，不设置存量豁免。
- 篇幅检查覆盖项目入口、共同规范及所有登记 README。历史功能记录、设计／计划和长篇参考手册通过链接按需查阅，仍受原格式、路径和覆盖检查。
- 默认阅读基础为 AGENTS、ARCHITECTURE、DEVELOPMENT_TESTING，叠加所选能力 README；相同实际文件只计算一次。完整门禁核对每项能力的默认清单，未知能力、缺文档、越界路径或超限失败。
- `python -m tools.architecture --context-for architecture --context-for acceptance-tests --report artifacts/architecture/doc-context-budget/context.json` 只输出路径、计量和合计，不加载业务、不执行 Git、不联网。完整门禁新增结构化预算结果。
- 政策格式严格校验；已有目标分支政策的限额只能保持或缩减，删除、缺字段或扩大限额失败。规则真实性和语义矛盾仍由人工审查。

## 新增依赖

只使用 Python 标准库；新工具代码登记到既有 architecture 能力，不改变业务依赖、允许关系、存量豁免或 CI 平台配置。

## 测试证据

2026-10-03，Windows／Python 3.12.8／UTF-8。源码基线 `3717263081ec079d0a38d2284919f329d312edef` 运行 `python -m unittest discover -s tests -v`：377 项、0 失败、7 项原环境跳过，97.214 秒。先运行 `python -m unittest tests.architecture.test_documentation_budget -v`：13 项因缺少功能而失败，其中实际旧门禁放过超长 README；实现后 13 项通过，1.217 秒。

- `python -m unittest discover -s tests/architecture -v`：77 项通过，2.651 秒。
- `python -m unittest discover -s tests -v`：390 项、0 失败、7 项跳过，97.988 秒。跳过项为真实 bt／Qlib、私有 P4 固定运行、三个符号链接环境用例和 Windows 8.3 短路径用例；本批不把这些记录为已验证。
- `python -m tools.architecture --base-ref 3717263081ec079d0a38d2284919f329d312edef --branch feature/doc-context-budgets --report artifacts/architecture/doc-context-budget/gate.json`：PASS，68 个源码模块、0 条存量违规，Import Linter 返回 0；40 份当前文档和 61 项能力的默认阅读清单均未超限。
- 上述两能力 `--context-for` 命令：PASS，去重后 5 份文档，227 行／11,138 字符；门禁不删除或截断任何原文。

baseline-tests.log／red-tests.log／green-tests.log／architecture-tests.log／full-tests.log、gate.json 与 context.json 保留在忽略的 `artifacts/architecture/doc-context-budget/`。此轮验证针对提交前候选代码；不可变源码提交及最终审查在收尾追加记录，验收日志不提交到版本库。

## 回滚方式

只回退本批工具、配置、测试和说明；原业务代码、历史研究、R001 记录与用户删除不纳入改动。保留本地验收证据；无外部上传或部署动作。

## 遗留问题

预算只覆盖声明的文档阅读范围，不能证明 AI 实际遵守读取顺序或避免所有语义矛盾。真实服务、Linux／远端 CI、本项目后续跨项目业务验收不属于本批本地工具交付。
