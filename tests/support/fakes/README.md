# 离线 worker 替身

## 职责与边界

在测试子进程中模拟 bt/Qlib worker 协议，包括原失败和超时行为。

## 文件导航

- [fake_bt_worker.py](fake_bt_worker.py)：bt worker。
- [fake_qlib_worker.py](fake_qlib_worker.py)：Qlib worker。

全局目录见 [测试导航](../../README.md)。

## 对外接口

worker 接口与原命令行、JSON/stdin/stdout 协议保持；由 test_bt_plugins.py/test_qlib_plugins.py 显式启动，不由 unittest 收集。

## 依赖规则

保持原标准库依赖及协议；不导入真实后端或其他测试用例。

## 数据与权限

仅显式测试参数、标准输入与临时输出；两个文件按原字节移动。

## 测试与验收

执行 `python -m unittest discover -s tests -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
