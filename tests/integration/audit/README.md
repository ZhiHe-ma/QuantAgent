# 旧引擎审计集成

## 职责与边界

使用原模型、网络、消息替身加载旧引擎，验证审计与失败路径。

## 文件导航

- [test_signal_audit_integration.py](test_signal_audit_integration.py)：审计集成用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

通过路径支持定位原 agent_engine.py，保持原动态测试加载和接口断言。

## 数据与权限

原合成输入与临时审计 SQLite；调用被替身限制。

## 测试与验收

执行 `python -m unittest discover -s tests/integration/audit -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
