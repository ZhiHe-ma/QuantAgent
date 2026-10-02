# 跨组件离线测试

## 职责与边界

验证工作流、P5 CLI/HTTP 与旧引擎审计协作，保留原替身和隔离条件。

## 文件导航

- [sec/README.md](sec/README.md)：SEC 工作流。
- [p5/README.md](p5/README.md)：P5 入口。
- [audit/README.md](audit/README.md)：旧引擎审计。
- [test_runner_composition.py](test_runner_composition.py)：运行器注入、默认目录、公开导出及独立进程启动兼容。
- [test_api_composition.py](test_api_composition.py)：原 HTTP 契约、应用工厂、无可选 HTTP 依赖的独立进程导入、存储授权与 worker 生命周期。

全局目录见 [测试导航](../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

通过既有公开接口协作，复用 tests.support；本目录不实现产品工作流。

## 数据与权限

固定合成输入与临时产物；真实服务按原条件隔离，不接入账号数据库。

## 测试与验收

执行 `python -m unittest discover -s tests/integration -t . -v`；目录分类证据见 [分类批次](../../docs/features/file-classification.md)，运行器分离证据见 [D001](../../docs/features/d001-runner-composition.md)。离线替身通过不构成真实后端或生产验收。

API 路由组装与兼容证据见 [D003](../../docs/features/d003-api-composition.md)。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
