# SEC 数据契约

## 职责与边界

验证标准化、版本、来源哈希和非法载荷拒绝；保持原 SEC 契约断言。

## 文件导航

- [test_sec_contracts.py](test_sec_contracts.py)：SEC 契约用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。直接运行脚本时按文件祖先引导所属包，再用共享 ROOT 验证仓库标记；--help 启动由专项回归覆盖。

## 依赖规则

依赖 sec_contracts、sec_client 的既有公共类型和 tests.support.sec_samples。

## 数据与权限

共享合成发行人载荷、SecResponse 与 DataPacket；无联网。

## 测试与验收

执行 `python -m unittest discover -s tests/contract/sec -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
