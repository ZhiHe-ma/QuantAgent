# 架构与文档门禁

## 职责与边界

标准库 AST 收集依赖，Git 只读命令比较目标提交，Import Linter 检查引用契约。工具不加载业务模块、不联网、不自动修改登记或豁免。

## 文件导航

[graph.py](graph.py)收集引用；[policy.py](policy.py)检查边界与豁免；[documentation.py](documentation.py)核对文档；[linter.py](linter.py)生成官方契约；[__main__.py](__main__.py)提供命令入口。

## 对外接口

安装 `requirements-test.txt`，从仓库根执行：

```bash
python -m tools.architecture --inventory
python -m tools.architecture --base-ref <目标提交> --branch <完整源分支> --report artifacts/architecture/report.json
```

inventory 只报告原始问题。完整检查以目标提交及实际源分支为准；`--mode merged` 用于目标分支提交。退出 0 表示门禁通过，仍可能是 PARTIAL_COMPLIANCE；退出 1 表示失败。

## 依赖规则

共同规则见[架构规范](../../docs/ARCHITECTURE.md)，允许引用及外部包来自[登记](../../docs/architecture/components.json)。检查细节集中在这里：

- 函数内和 TYPE_CHECKING 导入计入源码依赖，顶层脚本、私有引用、动态加载、未登记本地目标及第三方包也受检查。
- 包根导出访问计入引用；别名保留全部绑定，同名覆盖不能掩盖问题。保守误报应拆开命名，不添加宽泛豁免。
- 兼容启动门面可调用精确登记的 bootstrap，运行器及业务不能引用 bootstrap 或借包根获取它；新增允许项仍接受目标基线比较。D001 核对全部原登记能力的允许关系不变，不通过规则改变隐藏存量。
- Import Linter 的禁止引用启用 allow_indirect_imports，约束直接引用；独立性、分层和循环另行检查，同一能力内部可协作。
- 嵌套业务目录的 runtime/tests 不按顶层运行产物排除；新增独立 Agent/Skill 目录须登记。删除能力仍核对目标提交原归属。
- 首次基线与精确目标提交的扫描核对，后续只能缩减；报告保留官方配置、原始依赖图、豁免和结果。

## 数据与权限

只读仓库与指定 Git 提交，在显式报告路径及临时目录写检查产物；不连接数据库或外部服务。

## 测试与验收

运行 `python -m unittest discover -s tests/architecture -v` 验证检查器。产品离线测试见[测试导航](../../tests/README.md)；本次环境、结果和未测范围写入对应分支说明。

## 已知限制

静态分析不能穷举反射、对象重赋值或代码生成，也不能证明数据权限与业务语义。职责、说明真实性及运行时边界须人工审查，治理规则修改须代码所有者审查。
