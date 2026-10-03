# SEC 工作流集成

## 职责与边界

验证固定 SEC 配方、插件与 runner 的协作和产物；不迁移业务代码。

## 文件导航

- [test_sec_workflow.py](test_sec_workflow.py)：工作流用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。直接运行脚本时按文件祖先引导所属包，再用共享 ROOT 验证仓库标记；--help 启动由专项回归覆盖。

## 依赖规则

依赖 runner、SEC 公开接口和测试支持路径。

## 数据与权限

共享合成响应、固定配方、临时输出；无真实 SEC 取样。

## 测试与验收

执行 `python -m unittest discover -s tests/integration/sec -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
