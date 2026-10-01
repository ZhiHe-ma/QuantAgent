# SEC 研究规则

## 职责与边界

验证年度、单位、事实选择和派生分析规则，调用 sec_analysis 公共入口。

## 文件导航

- [test_sec_analysis.py](test_sec_analysis.py)：SEC 分析用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

依赖 sec_analysis、sec_contracts 的公开入口及共享 SEC 构造器。

## 数据与权限

合成公开财务证据及分析结果；不访问真实 SEC。

## 测试与验收

执行 `python -m unittest discover -s tests/unit/research -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
