# 公开契约测试

## 职责与边界

验证公开输入输出、拒绝条件和存储 schema；首批包含 SEC 契约与 SQL schema。

## 文件导航

- [sec/README.md](sec/README.md)：SEC 数据契约。
- [platform/README.md](platform/README.md)：审计 SQL schema。
- [test_api_contracts.py](test_api_contracts.py)：共享 API 类型、原导入路径的对象身份，以及不读取文件的配置和请求契约。
- [test_worker_ports.py](test_worker_ports.py)：有界读取与错误、完整 worker 参数、原 frozen 类型和函数签名、启动惰性绑定、独立重载，以及原默认配方实际消费自定义服务。

全局目录见 [测试导航](../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

依赖对应公开契约、正式 schema 和测试支持，保持正式文件原字节。

## 数据与权限

合成载荷与临时 SQLite；不使用真实账户。

worker 契约使用临时授权目录和原 fake worker 子进程，验证宿主接口；自定义工厂通过公开 getter 保存并在用例结束恢复，不留下全局配置变更。

## 测试与验收

执行 `python -m unittest discover -s tests/contract -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

API 契约来源与验证见 [D003](../../docs/features/d003-api-composition.md)。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
