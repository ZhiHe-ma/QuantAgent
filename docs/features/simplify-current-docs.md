# 当前文档精简

```json
{
  "branch": "docs/simplify-current-docs",
  "base_commit": "26281f3317b417c3e25dc215348ae8cabc3222a2",
  "components": ["architecture", "legacy-engine"],
  "readme_unchanged": {}
}
```

## 目标与非目标

缩短项目入口，集中共同规则与完整命令。历史设计、计划、既有分支说明和验收记录保留原内容；本次不改运行时、测试、权限或存量豁免。

## 涉及模块

architecture 更新规范、兼容声明及目录说明；legacy-engine 更新两个项目 README、使用说明和旧引擎导航。登记仅补齐文档资产归属。

## 接口或数据变化

README 保留最短入口，详细配置和命令统一在 USAGE.md；共同架构规则留在 ARCHITECTURE.md，扫描细节在工具 README。兼容声明链接精确验收，区分固定 P5/v2 与通用能力，避免旧结论被当成当前状态。产品 Python、CLI、HTTP 及数据契约不变。

## 新增依赖

不适用：仅维护 Markdown 及文档归属，没有新增运行或检查依赖。

## 测试证据

2026-10-02，Windows 11 10.0.22631、仓库外 Python 3.12.8、Import Linter 2.8、grimp 3.13。基于首个 JSON 中的提交验证本分支文档改动，使用原 `.venv/Lib/site-packages` 依赖，启用 PYTHONUTF8 与 PYTHONIOENCODING=utf-8。

- `python -m unittest discover -s tests -v`：283 项、0 失败、原 6 项跳过，57.818 秒。
- `python -m unittest discover -s tests/architecture -v`：47 项全部通过。
- `python -m tools.architecture --base-ref 26281f3317b417c3e25dc215348ae8cabc3222a2 --branch docs/simplify-current-docs`：PARTIAL_COMPLIANCE，42 条原存量，Import Linter 退出 0。
- 本地链接与锚点核对无错误；原中文进阶说明的 68 条命令/配置行全部保留，58 份未改 Markdown 的原字节哈希一致。登记差异仅为文档资产；运行时、测试和存量基线不变。

两份 README 从 426/421 行各减至 47 行；完整使用命令保留在 USAGE.md。原始日志、门禁 JSON、链接及哈希统计留在忽略的 `artifacts/architecture/documentation-simplification/`。

未运行：Linux/CI、真实模型/行情/消息、部署与生产验收。离线日志中的模型和消息使用原测试替身；本次不扩张已有验收范围。

## 回滚方式

按本分支提交恢复文档及文档资产登记；基线提交保留原入口内容。原工作区已有的项目方案删除改动不属于本次变更。

## 遗留问题

存量依赖与业务重构仍按原整改清单推进。旧设计和验收中的数字只对应当时版本，当前入口通过链接查阅，不重抄为最新结论。
