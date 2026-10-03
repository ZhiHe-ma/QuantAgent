# 文档篇幅与上下文阅读预算

```json
{
  "branch": "feature/doc-context-budgets",
  "base_commit": "3717263081ec079d0a38d2284919f329d312edef",
  "phase": "verified",
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
- 报告写入前拒绝与输入文档、治理配置或既有 Markdown／Python 文件冲突的目标；已有 JSON 报告可重新生成。写入同目录临时文件再原子替换目标，避免硬链接别名写穿原文。存在的目标政策与当前政策使用同一严格解析，拒绝 null 和重复键，允许 UTF-8 BOM；首次引入时仍允许目标文件不存在。

## 新增依赖

只使用 Python 标准库；新工具代码登记到既有 architecture 能力，不改变业务依赖、允许关系、存量豁免或 CI 平台配置。

## 测试证据

2026-10-03，Windows／Python 3.12.8／UTF-8。源码基线 `3717263081ec079d0a38d2284919f329d312edef` 运行 `python -m unittest discover -s tests -v`：377 项、0 失败、7 项原环境跳过，97.214 秒。先运行 `python -m unittest tests.architecture.test_documentation_budget -v`：13 项因缺少功能而失败，其中实际旧门禁放过超长 README；实现后 13 项通过，1.217 秒。

- `python -m unittest discover -s tests/architecture -v`：77 项通过，2.651 秒。
- `python -m unittest discover -s tests -v`：390 项、0 失败、7 项跳过，97.988 秒。跳过项为真实 bt／Qlib、私有 P4 固定运行、三个符号链接环境用例和 Windows 8.3 短路径用例；本批不把这些记录为已验证。
- `python -m tools.architecture --base-ref 3717263081ec079d0a38d2284919f329d312edef --branch feature/doc-context-budgets --report artifacts/architecture/doc-context-budget/gate.json`：PASS，68 个源码模块、0 条存量违规，Import Linter 返回 0；40 份当前文档和 61 项能力的默认阅读清单均未超限。
- 上述两能力 `--context-for` 命令：PASS，去重后 5 份文档，227 行／11,138 字符；门禁不删除或截断任何原文。

首个候选实现为 `fc0cd9ce36067210273952aef9f87f125938821c`。只读审查在真实临时环境复现报告覆盖原文、目标政策 null／重复键被放过两项 Important；新增两个真实 CLI／Git 回归，先观察 13 个子场景失败，再修复。额外观察并修复严格解析造成的目标政策 BOM 兼容失败。

修复提交 `c58120c43a0d3829386c07b3eb49647e5f0ac94d` 的架构测试 79 项通过，5.507 秒；完整回归 392 项、0 失败、7 项原环境跳过，101.350 秒。复核确认两项原问题闭合，但复现硬链接别名仍能覆盖原文；新增真实硬链接 CLI 用例先观察失败，再用临时文件与原子替换修复。

最终受验收源码 `bb86a89c3c9cbc0dc5bc6dbd3f4eac4f1ab7952c`：`python -m unittest discover -s tests/architecture -v` **80 项通过，5.564 秒**；`python -m unittest discover -s tests -v` **393 项、0 失败、7 项原环境跳过，101.333 秒**。上述门禁命令 PASS：68 个模块、0 条存量违规、Import Linter 返回 0。两能力阅读清单 PASS：5 份文档、227 行／11,221 字符。

同一只读审查席位复核最终修复，独立运行 16 项预算测试通过，4.168 秒；直接覆盖、非法目标政策、硬链接覆盖均闭合，无 Critical／Important／Minor。审查仅评价本批工具增量，既有业务设计未重新审查；既有离线用例已包含在完整回归中。真实 token／整段聊天计量和远端 CI 未验证。后续收尾提交只更新本分支说明，验收源码不变。

原始日志和结构化报告保留在忽略的 `artifacts/architecture/doc-context-budget/`；full-tests-final.log 保存 c58120c 的回归结果，最终结果以 full-tests-atomic.log／architecture-tests-final.log／gate-final.json／context-final.json／receipt.json 为准。review-red.log／review-bom-red.log／hardlink-red.log 保留修复前证据；验收日志不提交到版本库。

## 回滚方式

只回退本批工具、配置、测试和说明；原业务代码、历史研究、R001 记录与用户删除不纳入改动。保留本地验收证据；无外部上传或部署动作。

## 遗留问题

预算只覆盖声明的文档阅读范围，不能证明 AI 实际遵守读取顺序或避免所有语义矛盾。真实服务、Linux／远端 CI、本项目后续跨项目业务验收不属于本批本地工具交付。
