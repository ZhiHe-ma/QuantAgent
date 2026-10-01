# 架构规范与门禁首批交付

```json
{
  "branch": "feature/architecture-guardrails",
  "base_commit": "ccded244593942fc6de7c10983d6b0f795c36a47",
  "components": [
    "packet-contracts",
    "research-contracts",
    "sec-contracts",
    "plugin-ports",
    "daily-domain",
    "sec-domain",
    "quality-adapter",
    "daily-adapter",
    "outcome-adapter",
    "thesis-adapter",
    "isolated-runtime",
    "qlib-adapter",
    "bt-adapter",
    "sec-adapter",
    "p5-storage",
    "p5-domain",
    "p5-adapter",
    "runner",
    "agent-runtime",
    "p5-workflow",
    "http-api",
    "cli-composition",
    "startup",
    "compatibility-exports",
    "legacy-engine",
    "signal-audit",
    "architecture",
    "recipes",
    "plugin-catalog",
    "agent-catalog",
    "schemas",
    "policies",
    "acceptance-tests",
    "skill-sec-evidence-independent-review",
    "skill-sec-evidence-preparation",
    "skill-signal-data-health",
    "skill-thesis-tracker",
    "agent-data-health-agent",
    "agent-research-agent",
    "agent-sec-evidence-producer-agent",
    "agent-sec-evidence-review-agent",
    "agent-definitions"
  ],
  "readme_unchanged": {}
}
```

## 目标与非目标

将单向依赖、高内聚、低耦合和 Docs as Code 固定为登记、精确存量基线、测试与 CI；治理期间明确部分符合。首批不迁移运行时目录，不实现学习业务，不修改 OpenStock，也不执行 D001–D006 后续整改。

## 涉及模块

对现有生产模块和开发工具登记公开入口、允许依赖、README 与数据归属；为实际目录补齐 README 和导航，保留原有使用说明。规则位于架构规范，历史说明保留本次变更事实。

## 接口或数据变化

新增开发命令 python -m tools.architecture 及 version=1 的组件/基线 JSON。原有 Python/CLI/HTTP、配方和持久化均无行为变化。QuantAgent 公共域、OpenStock 私有域与受控学习更新边界写入规范。

## 新增依赖

仅开发依赖：Import Linter 2.8、Grimp 3.13 及锁定的 Rich/Markdown/Pygments 依赖；通过 requirements-test.txt 安装，不进入产品 runtime lock。官方工具与 AST 都不得导入或运行业务代码。

## 测试证据

实施基线：远端 main ccded244593942fc6de7c10983d6b0f795c36a47（重新获取，替代计划参考 bc9d647）；分支 feature/architecture-guardrails，Windows、Python 3.12。初始 30 个门禁测试先失败后通过；独立审查后扩充为 47 个测试，覆盖嵌套目录、包根属性、局部别名、未登记 SDK、独立 Skill、能力与资产删除。审查反例先产生 8 个失败与 1 个错误，修复后纳入完整通过结果。

最终本地命令 `python -m unittest discover -s tests -v`：279 项、0 失败、6 项跳过；其中原有 232 项未修改，新增 47 项门禁用例。跳过项为真实 Qlib/bt 后端 2 项、缺少私有 P4 固定运行样本 1 项、Windows 无符号链接权限 3 项。使用仓库外 Python 3.12，PYTHONUTF8=1，PYTHONPATH 指向本工作树 .venv/Lib/site-packages 的锁定依赖。初始仓库内 .venv 运行触发原有 Qlib 可执行文件目录负向测试的环境假设；换用仓库外解释器后通过，未放宽规则或更改产品/原有测试。

最终本地命令 `python -m tools.architecture --base-ref ccded244593942fc6de7c10983d6b0f795c36a47 --branch feature/architecture-guardrails --report artifacts/architecture/local-gate.json`：退出 0，PARTIAL_COMPLIANCE，42 个模块（35 个产品、7 个治理工具）、42 条精确存量违规、两组环；Import Linter 退出 0。`git diff --check` 无错误。原始日志在忽略的 artifacts/architecture；测试未导入业务来构建依赖图，未联网。首个被测实现提交为 2825bb37dae787338e2d7c9573a964601981ac77；最终复核还修正了同一业务能力内部文件不应被独立性契约拒绝的误报（失败用例先复现），补全 Agent 子目录文档并收录证据。最终完整测试为 279 项；门禁按完整目标与前次提交分别复核。

CI：提交 2825bb37dae787338e2d7c9573a964601981ac77 的 [PR 运行 36879145351](https://github.com/ZhiHe-ma/QuantAgent/actions/runs/36879145351) 四项均 success：Python 3.12 / ubuntu-latest、Python 3.12 / windows-latest、Architecture / Python 3.12 / ubuntu-latest、Architecture / Python 3.12 / windows-latest。运行步骤执行锁定依赖安装、上述完整离线测试，以及 `python -m unittest discover -s tests/architecture -v`、`python -m tools.architecture --report artifacts/architecture/ci-report.json`。草稿 [PR #21](https://github.com/ZhiHe-ma/QuantAgent/pull/21) 保持未合并。

远端保护：2026-10-01 使用现有 Git 登录读取管理权限（连接器自身无 admin 权限），确认此前 main 没有保护或 ruleset；只新增上述四项必需检查，绑定 GitHub Actions app_id=15368、strict=true，PUT 后 GET 回读 200，检查名称及提供方完全一致。管理员保持默认豁免（enforce_admins=false），未启用正式审批人数门禁；人工语义审核仍是仓库规范要求。额外启用管理员强制保护曾被自动审批审查拒绝，随后移除此额外设置并完成原定检查配置。回读证据在忽略的 artifacts/architecture/remote-protection-after.json，不保存凭据。

真实模型、行情抓取、真实 Qlib/bt 后端、部署和生产未验证。

## 回滚方式

撤销这次治理提交可删除开发工具、登记与文档门禁，不涉及数据迁移。远端若已启用保护，管理员只移除本批新加入的检查，保留此前设置；不得以关闭全部 CI 或放宽存量豁免作为回滚。

## 遗留问题

42 条存量违规按 D001–D006 分批整改；现有两组静态环不表示启动失败。语义、高内聚和数据写入归属仍需人工审查。首批门禁不等于完全符合、不等于部署或生产验收。
