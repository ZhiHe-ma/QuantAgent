# 架构与文档门禁

## 职责与边界

用标准库 AST、Git 只读命令及 Import Linter 检查源码与文档。扫描不导入或运行业务代码，也不联网。检查器分为 graph（收集）、policy（边界与豁免）、documentation（文档）、linter（官方工具）和命令入口。

## 文件导航

- `architecture`：[tools](../__init__.py)。
- `architecture`：[tools.architecture](__init__.py)。
- `architecture`：[tools.architecture.graph](graph.py)。
- `architecture`：[tools.architecture.policy](policy.py)。
- `architecture`：[tools.architecture.documentation](documentation.py)。
- `architecture`：[tools.architecture.linter](linter.py)。
- `architecture`：[tools.architecture.__main__](__main__.py)。

## 对外接口

安装 `requirements-test.txt`；`python -m tools.architecture --inventory` 输出原始依赖问题，不批准豁免。完整门禁要求 `--base-ref`、`--branch`，可用 `--mode merged` 检查目标分支提交，用 `--report artifacts/architecture/report.json` 保存配置、依赖图、豁免与结果。退出码 0 表示规则通过（可仍部分符合），1 表示检查失败。

## 依赖规则

允许依赖由 [components.json](../../docs/architecture/components.json) 精确登记；规则见 [架构规范](../../docs/ARCHITECTURE.md)。42 条存量违规仅按具体引用豁免，新增违规立即失败。

登记包含 external_dependencies 和独立目录发现根。业务/契约的未登记第三方包、未登记本地引用、通过点号导入访问包根导出均报错；删除能力也核对目标提交原归属。Import Linter 的禁止引用检查针对直接源码关系，传递依赖仍由独立性、分层与循环契约约束。

## 数据与权限

读取仓库源码、文档和指定 Git 目标提交，仅在显式报告路径与临时目录写报告或 Import Linter 配置；不连接数据库，不加载业务模块，不联网，不自动修改登记或豁免。

## 测试与验收

从仓库根目录运行 `python -m unittest discover -s tests -v`；架构门禁运行 `python -m tools.architecture --base-ref <目标提交> --branch <完整源分支>`。验收证据在对应分支说明；真实源、实验后端和生产环境未覆盖部分须单列。

## 已知限制

静态分析不证明运行时对象访问和数据归属语义；复杂反射不能穷举。动态加载及包根引用按规则拒绝，相关语义由人工复核。首次引入以精确目标提交扫描验证基线，之后仅允许收缩；治理规则修改需代码所有者审查。

导入别名采用保守集合，局部同名别名不能覆盖全局绑定；必要时拆开别名避免保守误报。运行时对象重赋值、反射或外部数据权限仍需人工复核。
