# 模块规则测试

## 职责与边界

验证单个模块的确定性规则与原子写入；包含 SEC 派生分析、P5 纯规则和运行器文件操作。

## 文件导航

- [research/README.md](research/README.md)：SEC 分析规则。
- [test_p5_ports.py](test_p5_ports.py)：严格 JSON、标识符、证据对象兼容与无存储访问的策略校验。
- [test_runner_atomic_write.py](test_runner_atomic_write.py)：运行器原子写入的 Windows 瞬时占用恢复、有限重试与失败时原字节保留；真实 Windows 用例在其他平台跳过。

全局目录见 [测试导航](../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

可使用对应模块公开接口和 tests.support；不读取其他模块私有变量。

原子写入单元直接验证运行器所属的内部 helper，使用合成临时文件与替身；跨组件用例使用公开入口。

## 数据与权限

研究对象及派生结果，输入为共享合成 SEC 数据。

## 测试与验收

执行 `python -m unittest discover -s tests/unit -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

Windows 写入回归的真实句柄证据与环境边界见 [D004](../../docs/features/d004-sec-contracts.md)。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
