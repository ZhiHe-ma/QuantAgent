# I003：整体分支说明与目标验收

```json
{
  "branch": "feature/i003-integration-acceptance",
  "base_commit": "ccded244593942fc6de7c10983d6b0f795c36a47",
  "phase": "verified",
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

固定被测版本：5242b112da76534449ed1ede7e5d5eeb0958981c，完整目标差异为 52 提交／197 已提交文件；本批仅 3 份 Markdown，产品沿用 5ce3bc9。初始 42 项的 violation_key 集合逐条匹配，基线、登记、预算和门禁规则 Git blob 保持，见 fixed-source-evidence.json。

`python -m unittest discover -s tests -v`：398 项，391 通过／7 跳过、0 失败，101.394 秒，退出 0（full-tests.log）。7 跳过为真实 bt／Qlib 解释器未配置、私有 P4 缺失、3 项 Windows 链接权限限制和 8.3 名称禁用，不记作通过。固定版本完整目标及本批增量门禁均 PASS（fixed-aggregate-gate.json、incremental-gate.json），不能只用新增文档自己的门禁代替整体检查。

一次独立只读整合审查：无新增 Critical／Important／Minor，既有 Minor 2 项延后。独立聚焦 9 项通过，1.313 秒、退出 0（reviewer-focused-tests.log）；42 项原始键、61 登记／52 受影响、唯一源分支说明及全部 README 决策核对通过。50 份固定资产字节保持（48 原路径、2 迁移），12 项导出、29 项插件顺序及原公开方法签名保持；I002 修复确在当前提交链，见 reviewer-static-checks.json、reviewer-compatibility-inventory.json、reviewer-final-review.md。未重复完整套件，也未用分离分支的结果拼成已发布版本。

当前进度：I001-01／02 由 I002 完成，I001-03／04 在本批完成；本地交付通过，Ready to merge 尚未建立。最终提交只补本文证据，产品保持上述固定版本。基础读取清单初始 231 行／11,488 字符通过，长篇历史与接口按职责分段读取；最终门禁继续应用原文档及默认阅读预算。

作者逐项承接审查者未裁决的范围，沿用已确认边界：

| Final Ruling | 理由与未验证代价 |
| --- | --- |
| 历史借入名 | 保留声明的所属导出及已记录别名；p5_coordinator.HandoffLedger 现为 Protocol，借入的 ApprovedRunRegistry 已移除。依赖这些名称的外部脚本可能不兼容，未验证。 |
| pickle／完整程序身份 | 沿用已有范围；迁移类型元数据和入口 source_sha256 不保证跨版本序列化或整个程序身份，旧载荷与完整版本追溯需另验。 |
| 自定义写回调 | 保留原显式 ports 消费约定，由所属适配器执行 dry-run 写守卫；实际引擎已测零写入，违规自定义适配器仍可能写文件。 |
| 远端状态 | 本次只重新核实 main SHA，当前 CI／保护、实际合并和部署未验。本地验收不能解除远端门禁，合入可能仍被拒绝。 |
| 真实集成及跳过项 | 保留离线范围；模型／新闻／消息、OpenStock、真实 bt／Qlib、私有 P4 与跳过平台场景无本次实证，现场兼容仍未知。 |
| 恢复与产品保证 | 沿用单机授权实例范围，不新增跨主机／磁盘损毁／消息恰好一次、学习／交易／生产保证；这些故障或业务仍需人工处理／另批开发验收。 |
| 原用户删除 | 不纳入本批提交、不恢复，保持唯一未暂存删除；若需将该删除交付，应单独处理，不能被本批静默纳入。 |

## 回滚方式

只回退本批汇总及导航改动；不重置主分支、重写历史基线、迁移数据或撤销历史审计。保留原始证据和用户删除。

## 遗留问题

I001 四项 Important 均已有对应固定版本证据，历史记录保留当时结论。当前源分支未上传；远端 Windows／Linux CI 和保护须在实际提交上核对，不能称已合入或生产通过。真实集成及恢复／产品未测范围见上表。

历史 Minor 延后：`git diff --check ccded244..5ce3bc9` 退出 2，legacy_workflows.py:316、tests/support/sec_samples.py:64 的末尾空行仍在（whole-diff-check.log）；不影响当前引用和业务验收，合入前整理。本批不扩展为产品格式清理。
