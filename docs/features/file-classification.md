# 开发与测试文件分类首批交付

```json
{
  "branch": "feature/file-classification",
  "base_commit": "3006e57069b7da92caf0f869c307bd4b0e7a1ea4",
  "components": ["architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "本批只增加分类文档和测试 README 登记；架构检查工具的接口、行为、依赖和权限未改变，其 README 现有说明继续有效。"
  }
}
```

## 目标与非目标

先写清文件归属，再试点整理六个测试文件和共享测试支持。保持已有产品与离线验收行为。本批不修改运行时源码、固定配方、正式 schema、权限或存量豁免，不实现学习业务。

## 涉及模块

architecture 增加 [文件归属规范](../DEVELOPMENT_TESTING.md) 和仓库内设计、实施计划；acceptance-tests 更新 [测试导航](../../tests/README.md)。架构工具 README 无需更新的逐项理由见首个 JSON 块。

## 接口或数据变化

新增测试支持接口 `repository_root(start: Path) -> Path`、`ROOT` 和共享 SEC 合成数据构造器，六个测试文件已按 [实施计划](../superpowers/plans/2026-10-02-file-classification.md) 迁移；两个 fake worker 原字节移入 support/fakes。产品 Python 导出、CLI、HTTP、公共数据契约不变。私人原始证据留在仓库外。

## 新增依赖

不新增第三方依赖。路径支持仅使用 Python 标准库；SEC 测试支持使用既有公共 SEC 数据类型。登记仅增加文档资产与 README 路径，不扩张允许依赖或豁免。

## 测试证据

基线提交 `3006e57069b7da92caf0f869c307bd4b0e7a1ea4`：Windows、仓库外 Python 3.12.8，`python -m unittest discover -s tests -v` 实测 279 项、0 失败、6 跳过。门禁为 PARTIAL_COMPLIANCE，42 条存量问题，Import Linter 退出 0。

F1：2026-10-02，在同一 Windows/Python 环境运行本地引用检查，106 个链接、0 个缺失；运行 `python -m tools.architecture --base-ref 3006e57069b7da92caf0f869c307bd4b0e7a1ea4 --branch feature/file-classification`，结果为 PARTIAL_COMPLIANCE、42 条已登记问题、Import Linter 退出 0、无文档错误。原始报告保存在本地忽略产物目录。

F3：同环境执行 `python -m unittest discover -s tests -p test_support_paths.py -v`，先因缺少 tests.support 模块失败，随后三个路径用例通过。原主命令实测 282 项、0 失败、6 跳过，50.972 秒。原 279 项只按六项模块前缀映射，零缺失、零重复；新增三个路径用例单列。共享 SEC 构造器源片段、两个 fake worker 原字节保持。

子目录命令 `python -m unittest discover -s tests/unit -t . -v` 实测 3 项；contract 同类命令 13 项；integration 同类命令 22 项，均零失败。首次 contract 命令未指定包根，platform 子包遮住标准库，改为明确 `-t .` 后通过；已同步各 README。bt 专项 8 项、跳过 1，Qlib 专项 5 项、跳过 1，均零失败，保留原真实后端启用条件。

首轮被测内容对应提交 `bb63419c38c7af411827dc39f1c222531bbf9ebb`，基于 `3006e57069b7da92caf0f869c307bd4b0e7a1ea4`。环境是 Windows 11 10.0.22631、Python 3.12.8，Import Linter 2.8、grimp 3.13、jsonschema 4.25.1。用例清单、子目录实际标识、worker 哈希和报告在本地忽略产物目录留存。

独立审查发现一项 Important：共享 ROOT 的导入早于原路径引导，导致平铺测试的直接文件入口失败。新增启动回归，六个平铺 --help 子例先因 ModuleNotFoundError 失败；按包或直接文件运行选择同一共享源的导入路径后通过。23 个平铺调用者恢复启动兼容，并补齐六个已分类文件的祖先包引导，最终用例 `test_test_scripts_start_from_another_cwd` 覆盖 12 个子例；六个分类入口也先失败再修复。资源仍由共享四标记规则定位，没有产品行为变化。

修复平铺入口后原全套命令实测 **283 项、0 失败、6 跳过，55.896 秒**；随后扩大同一入口用例到六个分类文件，最终全套实测 **283 项、0 失败、6 跳过，58.508 秒**。原 279 项仍全部对应；数量比计划增加 1，是独立审查回归测试，原三项路径测试保持。先前 282 项日志保存在 task5-unittest-before-review.log。没有 Critical 或 Minor；按单次修复流程验证，不另派第二次审查。

当前架构门禁仍为 42 条已登记问题，Import Linter 退出 0；16 个无关工作树的分支、完整提交及未提交状态与基线完全一致；原治理分支引用保留。运行时源码、正式配方、SQL、schema、权限及 legacy-baseline 无差异，登记只增加文档资产和 README 路径。

CI/Linux、生产、真实模型、真实行情和真实外部后端未运行，本批仅验收 Windows 离线整理。原六项跳过为真实 bt、真实 Qlib、私有 P4 运行缺失，以及三个 Windows symlink 权限条件；没有新增跳过。

## 回滚方式

整理提交可逐个 `git revert`，按实施计划的六项路径映射反向恢复；两份 fake worker 只移动，原字节保持。原治理分支保留指向基线，不自动合并。仓库外导航原字节与 SHA-256 在本地忽略的 `artifacts/architecture/file-classification/vault-before/` 留存，由本地验收记录指向；不上传私人资料。

## 遗留问题

仍为部分符合：42 条存量问题和两组循环未整改；平铺测试中未进入试点的文件留待对应业务能力整改。OpenStock TypeScript 架构门禁另批落实。离线测试通过不能替代 CI 或生产验收。
