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
    "skill-thesis-tracker"
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

实施基线：远端 main ccded244593942fc6de7c10983d6b0f795c36a47（重新获取，替代计划参考 bc9d647）；分支 feature/architecture-guardrails，Windows、Python 3.12。初始 30 个门禁测试先失败后通过；独立审查后扩充为 46 个测试，覆盖嵌套目录、包根属性、局部别名、未登记 SDK、独立 Skill、能力与资产删除。审查反例先产生 8 个失败与 1 个错误，修复后纳入完整通过结果。

最终本地命令 `python -m unittest discover -s tests -v`：278 项、0 失败、6 项跳过；其中原有 232 项未修改，新增 46 项门禁用例。跳过项为真实 Qlib/bt 后端 2 项、缺少私有 P4 固定运行样本 1 项、Windows 无符号链接权限 3 项。使用仓库外 Python 3.12，PYTHONUTF8=1，PYTHONPATH 指向本工作树 .venv/Lib/site-packages 的锁定依赖。初始仓库内 .venv 运行触发原有 Qlib 可执行文件目录负向测试的环境假设；换用仓库外解释器后通过，未放宽规则或更改产品/原有测试。

最终本地命令 `python -m tools.architecture --base-ref ccded244593942fc6de7c10983d6b0f795c36a47 --branch feature/architecture-guardrails --report artifacts/architecture/local-gate.json`：退出 0，PARTIAL_COMPLIANCE，42 个模块（35 个产品、7 个治理工具）、42 条精确存量违规、两组环；Import Linter 退出 0。`git diff --check` 无错误。原始日志在忽略的 artifacts/architecture；测试未导入业务来构建依赖图，未联网。代码版本为上述基线加本分支本次提交内容；提交后复核结果另行补录。

CI：待分支发布后验证；远端 main 当前 protected=false，连接器无管理权限（保护 API 返回 403），浏览器管理页未登录，必需检查尚未启用。真实模型、行情抓取、真实 Qlib/bt 后端、部署和生产未验证。

## 回滚方式

撤销这次治理提交可删除开发工具、登记与文档门禁，不涉及数据迁移。远端若已启用保护，管理员只移除本批新加入的检查，保留此前设置；不得以关闭全部 CI 或放宽存量豁免作为回滚。

## 遗留问题

42 条存量违规按 D001–D006 分批整改；现有两组静态环不表示启动失败。语义、高内聚和数据写入归属仍需人工审查。首批门禁不等于完全符合、不等于部署或生产验收。
