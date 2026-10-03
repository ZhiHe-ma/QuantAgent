# I003：整体分支说明与目标验收

```json
{
  "branch": "feature/i003-integration-acceptance",
  "base_commit": "ccded244593942fc6de7c10983d6b0f795c36a47",
  "phase": "implementing",
  "components": [
    "sec-contracts",
    "sec-response-contracts",
    "signal-report-contracts",
    "quality-adapter",
    "daily-adapter",
    "outcome-adapter",
    "worker-ports",
    "worker-composition",
    "isolated-runtime",
    "qlib-adapter",
    "bt-adapter",
    "sec-adapter",
    "sec-source-identities",
    "p5-ports",
    "p5-composition",
    "p5-storage",
    "p5-domain",
    "p5-adapter",
    "runner",
    "default-composition",
    "p5-workflow",
    "api-contracts",
    "api-factory-port",
    "api-composition",
    "http-api",
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
    "agent-definitions",
    "legacy-ports",
    "legacy-workflows",
    "legacy-composition",
    "signal-audit-contracts",
    "recovery-contracts",
    "recovery-domain",
    "recovery-storage",
    "recovery-package"
  ],
  "readme_unchanged": {
    "architecture": "本批只新增整合说明及文档导航，门禁接口、规则、能力登记和预算未改变，tools/architecture/README.md 无需再次更新；整体目标差异中该 README 已更新。"
  }
}
```

## 目标与非目标

用户同意补齐整体分支说明、对齐实际目标并做固定版本整合验收。本文是当前完整源分支的汇总入口；[I001](i001-integration-review.md)、[I002](i002-monitor-dry-run.md)及各批记录保留原范围和结果，不重写历史。

实施步骤：核实远端目标／重放初始扫描 → 覆盖全部受影响能力及 README 决策 → 固定提交的离线测试、完整门禁与一次独立只读整合审查。仅补文档导航，不修改产品、测试、规则、权限或历史基线；不上传、合并或部署。原用户删除保持未暂存。

## 涉及模块

相对目标 main 的完整差异涉及 52 项能力，JSON 逐项登记；它们的所属 README 均已在整体差异中新增或更新。本批只改整合索引，JSON 另列 architecture 工具 README 无需再次更新的理由，便于后续增量提交核对。代码范围、公开入口及数据归属仍以[能力登记](../architecture/components.json)为准；本文不复制每项接口。

历史入口：[治理](architecture-guardrails.md)、[文件分类](file-classification.md)、[D001](d001-runner-composition.md)、[D002](d002-p5-boundaries.md)、[D003](d003-api-composition.md)、[D004](d004-sec-contracts.md)、[D005](d005-adapter-contracts.md)、[D006](d006-legacy-workflows.md)、[文档预算](doc-context-budgets.md)、[R001](r001-recovery-resume.md)、[R002](r002-recovery-read-snapshot.md)、[I002](i002-monitor-dry-run.md)。共同规范：[架构](../ARCHITECTURE.md)、[文件与文档归属](../DEVELOPMENT_TESTING.md)。

## 接口或数据变化

完整变更建立精确架构／文档门禁，按能力拆分组装、契约、适配器及旧工作流，增加单机恢复与文档读取预算；现有公开 Python／CLI／HTTP／固定配方行为由兼容测试核对。I002 恢复 Monitor 只读预览、同批／跨轮去重与限次，并固定契约测试时钟。QuantAgent 公共研究与 OpenStock 私有数据的归属保持；学习业务、自动规则修改和交易未实现。

本批仅添加汇总和阅读导航。Ruling: 实际整合目标使用本次 fetch 核实的 origin/main ccded244，保留落后的本地 main c445fac 和历史 origin_commit — 两者相差四个已在远端 main 的提交；若远端推进，必须对新的实际目标重新验收。

## 新增依赖

本批无新增依赖、能力、豁免或允许引用。整个范围新增锁定开发依赖 Import Linter 2.8（见 [requirements-architecture.txt](../../requirements-architecture.txt)，由 requirements-test.txt 引入），现有 Python 3.12 Windows／Linux CI 执行离线测试及门禁；真实实验后端继续按原开关隔离。本地通过、远端 CI、部署和生产分别记录。

## 测试证据

2026-10-04，Asia/Singapore／Windows 11／Python 3.12.8／SQLite 3.45.3／UTF-8。原始产物：忽略的 artifacts/integration/i003-integration-acceptance/；日志不作为远端 CI 或生产证据。

目标核对：git fetch --no-tags --no-recurse-submodules origin refs/heads/main 成功，FETCH_HEAD、origin/main 和当前源分支 merge-base 均为 ccded244593942fc6de7c10983d6b0f795c36a47。初始治理 2825bb37 的原登记对该目标重新静态扫描：42 项违规、两组环，与原 42 项基线一致；当前基线零豁免且 origin_commit 未修改，见 target-and-coverage.json。

旧 I002 说明用于整个目标差异时，python -m tools.architecture --base-ref ccded244593942fc6de7c10983d6b0f795c36a47 --branch feature/i002-monitor-dry-run 返回 1：48 项能力说明遗漏，0 引用违规／循环，Import Linter 返回 0（before-aggregate-gate.json／log）。这是汇总门禁的真实负例，不是产品测试失败。

汇总后完整门禁：`python -m tools.architecture --base-ref ccded244593942fc6de7c10983d6b0f795c36a47 --branch feature/i003-integration-acceptance --report artifacts/integration/i003-integration-acceptance/aggregate-gate.json`，退出 0，68 模块、0 存量／违规／循环，Import Linter 返回 0。使用旧本地目标 c445fac 的同一门禁退出 1，仅报告初始目标不匹配（wrong-local-target-gate.json）；规则未放宽。加 `--branch main --mode merged` 的文档检查退出 0（merged-mode-gate.json），仅为目标分支模式模拟，未实际合并。

当前进度：目标、初始扫描、52 项覆盖及正反门禁已核对；固定提交的完整离线回归和独立审查待验收。基础读取清单 231 行／11,488 字符通过，长篇历史与接口按职责分段读取。

## 回滚方式

只回退本批汇总及导航改动；不重置主分支、重写历史基线、迁移数据或撤销历史审计。保留原始证据和用户删除。

## 遗留问题

I001-01／02 已在 I002 固定源码验收完成；I001-03／04 本批核实中，完成需以本次固定提交和完整目标差异的门禁／审查为准。当前未运行远端 Windows／Linux CI、真实模型／新闻／消息、OpenStock 联调、跨主机、部署或生产验收；真实 bt／Qlib、私有 P4 及 Windows 特定权限的跳过不记作通过。

历史 Minor 延后：`git diff --check ccded244..5ce3bc9` 退出 2，legacy_workflows.py:316、tests/support/sec_samples.py:64 的末尾空行仍在（whole-diff-check.log）；不影响当前引用和业务验收，合入前整理。本批不扩展为产品格式清理。
