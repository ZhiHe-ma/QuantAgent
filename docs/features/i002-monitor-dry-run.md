# I002：Monitor 试跑兼容与测试时钟

```json
{
  "branch": "feature/i002-monitor-dry-run",
  "base_commit": "6475cbc7dea5cb6993d3cb9f002bcec623abc9e4",
  "phase": "verified",
  "components": ["legacy-workflows", "acceptance-tests", "recovery-storage", "architecture"],
  "readme_unchanged": {
    "architecture": "本批仅按既有格式添加修复记录，门禁接口、能力归属、规则与文档预算未变，tools/architecture/README.md 无需更新。"
  }
}
```

## 目标与非目标

用户同意修复 [I001](i001-integration-review.md) 的 I001-01／02：Monitor dry-run 的预览、跨轮去重与有限重试，以及凌晨不稳定的契约用例。复用隔离工作区和既有规范；原用户删除保留。

正式恢复使用非 dry-run 流程；试跑沿用既有只读预览入口，读取去重／失败资料并在内存保留进度，不创建恢复日志或锁。直接调用正式恢复函数传 dry-run 时拒绝执行，和 Daily 保持一致。正常恢复、CLI、HTTP、配方、依赖和数据权限保持。整体分支说明、实际目标基线、远端 CI、上传、合并和部署另批处理。

## 涉及模块

[工作流导航](../../quantagent_platform/README.md)、[恢复契约](../../quantagent_platform/recovery/README.md)、[测试导航](../../tests/README.md)。本批在既有测试文件补多轮试跑回归、正式恢复入口边界及固定时钟，不创建新功能目录。

## 接口或数据变化

根因是 Monitor 总在绑定恢复存储时进入正式恢复函数，dry-run 分支忽略原去重与预览；Daily 已正确分流。修复从公开工作流入口分流，正式恢复明确拒绝 dry-run。时钟用例统一控制完整流水线与直接审计的时间来源，保留真实 SQLite、质量注入及交付断言。

## 新增依赖

无新增依赖、能力、允许引用或豁免；测试外部行情／模型为替身，业务文件和 SQLite 仍使用真实临时对象。

## 测试证据

2026-10-04，Asia/Singapore／Windows 11（10.0.22631）／Python 3.12.8／SQLite 3.45.3／UTF-8。基线 6475cbc：`python -m unittest tests.test_dry_run tests.integration.test_monitor_recovery tests.contract.test_legacy_ports -v`，21 项、1 错误、3.347 秒，退出 1；错误为 I001-02，日志在忽略的 `artifacts/integration/i002-monitor-dry-run/baseline.log`。

合并阅读清单 341 行／19,355 字符超过既有预算，按职责分段：工作流＋恢复 5 份、239 行／14,233 字符；测试＋门禁 5 份、229 行／11,377 字符，均通过。未放宽预算或删去必需规范。

先测后改：新增三项 Monitor 方法、七个行为失败，0.055 秒；固定 02:00／09:00 的旧契约用例在凌晨复现 SQLite 时间约束错误，1 项／1 错误，1.048 秒。日志为 `monitor-red-complete.log`、`clock-red.log`，均退出 1，未放宽约束。

修复后同一基线命令通过：24 项、0 失败、3.546 秒，退出 0，日志 `targeted-green.log`。首次固定源码 7fc404138b6a9e5f47751171f0ad7c9d5d35f023：`python -m unittest discover -s tests -v`，398 项、391 通过／7 跳过、101.323 秒，退出 0，日志 `full-tests.log`；本批增量门禁通过。RED 为基线加未提交回归测试的工作区，不是已提交源码验收。

独立审查发现 1 项 Important：同批重复 ID／指纹导致预览重复推理，已有失败 2／上限 3 时还能追加 3 次。复现见 `reviewer-duplicate-probe.log`；扩充现有公开入口测试后，2 项方法／3 个失败，0.073 秒，退出 1（`batch-red.log`）。仅 dry-run 候选批新增 ID／指纹去重，修复后同一基线命令 24 项通过，3.571 秒，退出 0（`targeted-batch-green.log`）。

最终源码：35b65c45d447ff8c8cdab6fbc80c8e8259e43c4a。`python -m unittest discover -s tests -v`：398 项，391 通过／7 跳过、0 失败、100.842 秒，退出 0（`full-tests-final.log`）；包含既有公开 Python 导出、CLI、HTTP 与固定配方兼容用例。7 项跳过为真实 bt／Qlib 解释器未配置、私有 P4 样本缺失、3 项 Windows 链接权限限制和 8.3 名称禁用，不记作通过。

本批门禁：`python -m tools.architecture --base-ref 6475cbc7dea5cb6993d3cb9f002bcec623abc9e4 --branch feature/i002-monitor-dry-run --report artifacts/integration/i002-monitor-dry-run/gate-source.json`，68 模块、0 违规／0 环、Import Linter 退出 0（54 条契约通过）。最终阅读清单：工作流＋恢复 243 行／14,541 字符，测试＋门禁 231 行／11,488 字符，均在原预算内。

独立复审固定范围 7fc4041 → 35b65c4：5 项聚焦回归通过，0.667 秒、退出 0（`reviewer-batch-green-focused.log`）；两条原探针各调用模型 1 次且文件字节不变（`reviewer-batch-green-probes.log`）。Critical／Important／Minor 均为 0，原 Important 已闭环，I001-01／02 在本批完成。本记录的最终提交仅补证据，源码保持上述版本；日志均在上述忽略目录，不作为远端 CI 或生产证据。

## 回滚方式

回退本批源码、测试及当前说明；没有数据库迁移、业务数据修正或外部交付。保留原始证据及用户删除。

## 遗留问题

I001-03／04 的整体说明与目标起点尚未处理，不能把本批增量门禁当作整体可合入结论。真实模型／新闻／消息、Linux／远端 CI、跨主机、部署与生产未验证。
