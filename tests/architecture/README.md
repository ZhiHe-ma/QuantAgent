# 架构与文档门禁测试

## 职责与边界

验证登记、依赖方向、精确存量基线和文档同步的正反例。

## 文件导航

- [test_guardrails.py](test_guardrails.py)：门禁回归。

全局目录见 [测试导航](../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

依赖 tools.architecture 公共检查入口；原特殊仓库根定位保持。

## 数据与权限

临时模拟仓库与静态源码；不联网或执行业务模块。

## 测试与验收

执行 `python -m unittest discover -s tests/architecture -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
