# I001：整体集成审查

```json
{
  "branch": "feature/i001-integration-review",
  "base_commit": "fa2f6ea0fbde1f6f2f5a68b294f637055aab9bea",
  "phase": "verified",
  "components": ["architecture"],
  "readme_unchanged": {
    "architecture": "本批仅添加整体审查与验收记录；门禁接口、能力登记、文档格式及权限未改变，tools/architecture/README.md 无需更新。"
  }
}
```

## 目标与非目标

用户同意核对整体差异、恢复兼容性与验收真实性，产出可合入项及阻塞清单。本分支仅添加审查文档，复用现有规范与历史记录，不修改产品或测试，不上传、合并或部署；原用户文件删除保留。

固定产品审查范围：本地 main `c445fac845c1ebbdfcd21745160bbcbded23c3c2` → `fa2f6ea0fbde1f6f2f5a68b294f637055aab9bea`，51 个提交、194 个文件，涵盖治理与分类、D001–D006、文档预算、R001/R002。以上产品范围与 JSON 声明的文档分支改动分别验收。

## 涉及模块

审查依据与职责见[架构规范](../ARCHITECTURE.md)、[文件归属](../DEVELOPMENT_TESTING.md)、[能力登记](../architecture/components.json)、[测试导航](../../tests/README.md)及[恢复说明](../../quantagent_platform/recovery/README.md)。独立审查者只读检查固定提交；执行者验证门禁、原资产和故障复现。

## 接口或数据变化

无产品接口或数据变更。当前已确认的兼容证据：原 50 份固定资产中 48 份原路径 Git blob 保持、2 份 fake worker 迁移且字节保持；包根 12 项导出与默认 29 个插件顺序保持；RecipeRunner、SignalAuditStore、QuantAgent 原公开方法签名分别 4／6／15 项保持。AST／字节比较证明对应形态，行为仍由实际测试和人工审查核对。

可继续纳入交付的内容：能力登记与单向引用约束、文档预算、D001–D006 边界拆分及恢复存储；源码图无循环／违规、Import Linter 返回 0。整合结论仍受下列阻塞项限制。

| 编号 | 严重性 | 阻塞及处理方向 |
| --- | --- | --- |
| I001-01 | Important | [Monitor dry-run](../../quantagent_platform/legacy_monitor_recovery.py)每轮重置 seen、跳过去重资料、忽略结果和异常，导致重复模型调用、丢失预览及解析重试上限失效。恢复原只读预览、跨轮内存去重与有限重试，并新增多轮回归。 |
| I001-02 | Important | [新增契约用例](../../tests/contract/test_legacy_ports.py)第 96 行把开始时间固定为当天 08:00，结束时间用实际时钟；凌晨触发真实 SQLite 时间顺序约束。使用一致的固定测试时钟，保留真实存储与注入断言。 |
| I001-03 | Important | R002 说明只登记最后一批能力，完整主分支差异遗漏 49 项受影响能力。为最终实际源分支准备一份覆盖全部改动与 README 决策的说明，链接既有批次记录。 |
| I001-04 | Important | 本地 main 早于[初始基线](../architecture/legacy-baseline.json)绑定的 ccded244，首次治理目标检查失败。核实实际 PR 目标并复核初始扫描证据；保留历史起点、零豁免与已有依赖规则，不能仅重写提交标记。 |

Minor：全范围 `git diff --check` 返回 2，legacy_workflows.py 第 303 行及 sec_samples.py 第 64 行有新增末尾空行；不影响当前依赖检查，合入前整理即可。

## 新增依赖

无新增运行或开发依赖、能力、豁免或允许引用；审查脚本与原始报告位于忽略的本地产物目录，未加入产品或 CI。

## 测试证据

2026-10-04，Asia/Singapore／Windows／Python 3.12.8／SQLite 3.45.3／UTF-8；全部产品命令执行于固定源码 fa2f6ea，原始证据在 `artifacts/integration/i001-review/`。

- `python -m unittest discover -s tests -v`：395 项，387 通过、1 错误、7 跳过，101.542 秒，退出 1，见 full-tests.log。错误为 I001-02；历史 395 项通过不能替代此次结果。
- `python artifacts/integration/i001-review/reproduce_clock.py`：原用例固定在 +08:00 的 02:00 时错误、09:00 时通过；真实临时 SQLite，见 clock-reproduction.json／log。脚本退出 0 表示复现成立。
- `python -B artifacts/integration/i001-review/reproduce_monitor_dry.py`：执行原 main Monitor 方法与当前恢复流程，外部能力全部合成；同新闻两轮模型调用为旧 1／新 2，已处理 ID 为旧 0／新 2，四轮无效解析为旧 3／新 4。当前预览均为 0 字符；没有实际模型、网络或业务文件写入。见 monitor-dry-reproduction.json／log，脚本退出 0 表示回归成立。
- `python artifacts/integration/i001-review/inspect_compatibility.py`：上述 50 份资产、12 项导出、29 个插件及原方法签名保持，见 compatibility-inventory.json；只读 Git blob 与 AST。
- `python -m tools.architecture --base-ref c445fac845c1ebbdfcd21745160bbcbded23c3c2 --branch feature/r002-recovery-read-snapshot --report artifacts/integration/i001-review/main-target-gate.json`：FAIL，初始基线起点不匹配及 49 项分支说明遗漏；68 个源码模块、0 存量／引用违规／循环，Import Linter=0，预算通过。
- 同一门禁将目标换成缓存 `ccded244593942fc6de7c10983d6b0f795c36a47`：仍 FAIL，49 项说明遗漏，起点不匹配消失，见 cached-main-gate.json。缓存不代表本次已获取远端状态，不能用切换目标掩盖整体说明缺口。
- `git diff --check c445fac845c1ebbdfcd21745160bbcbded23c3c2..fa2f6ea0fbde1f6f2f5a68b294f637055aab9bea`：退出 2，上述两项末尾空行，见 diff-check.log。
- 本批初始阅读清单 `python -m tools.architecture --context-for architecture --context-for acceptance-tests`：5 份、229 行／11,377 字符，PASS。源码及各阶段历史按需分段审查。
- `python -m tools.architecture --base-ref fa2f6ea0fbde1f6f2f5a68b294f637055aab9bea --branch feature/i001-integration-review --report artifacts/integration/i001-review/document-gate.json`：本批新增文档门禁 PASS，68 个模块、0 存量，Import Linter=0；只验收审查记录这一增量。

独立审查在固定范围分四轮核对组装／公开兼容、恢复及数据所属操作、门禁与文档、测试和原资产；未修改工作树或重复完整套件。结论为 **Ready to merge: No**，无已证实 Critical，4 项 Important、2 处 Minor 末尾空行。执行者独立复现时钟与 dry-run 问题，接受四项发现；上述产品／测试未修改。新审查文档自己的门禁通过不解除产品整体门禁失败。

范围排除由执行者逐项裁定：

| 排除项 | 裁定与理由 |
| --- | --- |
| 历史模块借入名 | 接受本次兼容范围为声明导出、所属公开对象及已记录别名；例如 p5_coordinator.HandoffLedger 现为 Protocol，借入的 ApprovedRunRegistry 名称已移除。依赖这些借入名的外部脚本未验证，保留兼容风险。 |
| 跨版本 pickle／完整源码身份 | 接受原记录范围；迁移类型的模块元数据及 entry-file source_sha256 不能证明整个版本兼容或身份，仍未验证。 |
| 远端 CI／保护 | 本地文件及缓存不能裁定当前远端状态，后续独立核对。 |
| 真实服务、跳过样本、跨主机、物理灾难、消息恰好一次、学习、交易、生产 | 沿用已批准的单机离线范围；这些能力没有本轮实测证据。 |
| 原用户删除 | 不在提交审查范围；保持未暂存，不恢复或纳入本批。 |

## 回滚方式

仅回退本批新增审查文档；没有产品、测试、配置或数据迁移。保留原始验收证据及用户删除，不撤销任何已交付消息或历史审计。

## 遗留问题

当前结论：整体版本暂不能合入，I001-01～04 待处理。优先恢复 Monitor dry-run 兼容性、使契约测试时钟独立，再确认目标并准备整体分支说明；改动后重新验收实际提交，随后进入远端 Windows/Linux CI。7 项跳过仍是未指定真实 bt／Qlib 解释器、私有 P4 样本缺失、三项 Windows 链接权限限制及 8.3 名称禁用；不记作通过。

本次未 fetch、回读远端保护、运行远端 Windows/Linux CI、真实外部服务、OpenStock 联调、部署或生产验收。跨主机／磁盘损毁／消息恰好一次、学习与交易沿用原范围排除。默认 SQLite 短读取可能延迟提交及完成记录保留策略仍是[恢复说明](../../quantagent_platform/recovery/README.md)中的后续事项。
