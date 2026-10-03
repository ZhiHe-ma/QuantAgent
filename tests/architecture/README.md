# 架构与文档门禁测试

## 职责与边界

验证登记、依赖方向、精确存量基线和文档同步的正反例。

## 文件导航

- [test_guardrails.py](test_guardrails.py)：门禁回归，包括合法启动注入、非法核心反向引用、包根绕过及原登记关系保持。
- [test_p5_boundaries.py](test_p5_boundaries.py)：静态检查 P5 校验/工作流不引用具体存储或私有成员；ports 仅允许 Packet，SEC 来源别名仅允许纯响应契约。原启动矩阵按 D001 前 42 项能力固定，新增能力不混入历史范围。
- [test_api_boundaries.py](test_api_boundaries.py)：检查源码无循环、API 不相互导入或调用存储私有成员，共享契约与工厂接口不引用 IO、工作流或运行后端。
- [test_sec_boundaries.py](test_sec_boundaries.py)：检查 SEC 响应契约仅用标准库、标准化不引用具体客户端；函数内和类型检查导入均按源码统计。
- [test_adapter_boundaries.py](test_adapter_boundaries.py)：检查适配器使用所属共享契约，Qlib/bt 使用公开 ports，不引用具体质检或运行适配器；纯契约不引入 IO、SDK 或动态导入。

全局目录见 [测试导航](../README.md)。

[test_legacy_boundaries.py](test_legacy_boundaries.py)静态拒绝旧入口越界和动态导入，并检查 legacy ports 无 IO、工作流不访问具体适配器或私有字段。

[test_recovery_boundaries.py](test_recovery_boundaries.py) 静态核对恢复契约与纯规则不引用 IO 或存储实现。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。

## 依赖规则

依赖 tools.architecture 公共检查入口；原特殊仓库根定位保持。

## 数据与权限

临时模拟仓库与静态源码；不联网或执行业务模块。

## 测试与验收

执行 `python -m unittest discover -s tests/architecture -v`；分类证据见 [分类批次](../../docs/features/file-classification.md)，启动规则回归见 [D001](../../docs/features/d001-runner-composition.md)。静态检查不构成真实后端或生产验收。

API 边界整改与实际门禁结果见 [D003](../../docs/features/d003-api-composition.md)。

## 已知限制

其他平铺用例仍按测试导航保留。当前治理状态见[架构规范](../../docs/ARCHITECTURE.md)，存量问题不因目录整理消除。
