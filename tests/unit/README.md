# 模块规则测试

## 职责与边界

验证单个业务模块的确定性规则；首批是 SEC 派生分析，不编排完整用户流程。

## 文件导航

- [research/README.md](research/README.md)：SEC 分析规则。
- [test_p5_ports.py](test_p5_ports.py)：严格 JSON、标识符、证据对象兼容与无存储访问的策略校验。

全局目录见 [测试导航](../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

可使用对应模块公开接口和 tests.support；不读取其他模块私有变量。

## 数据与权限

研究对象及派生结果，输入为共享合成 SEC 数据。

## 测试与验收

执行 `python -m unittest discover -s tests/unit -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
