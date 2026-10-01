# P5 CLI 与 HTTP 集成

## 职责与边界

验证 P5 命令行、结果接口和任务入口的兼容行为。

## 文件导航

- [test_p5_cli_api.py](test_p5_cli_api.py)：P5 CLI/API 用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。直接运行脚本时按文件祖先引导所属包，再用共享 ROOT 验证仓库标记；--help 启动由专项回归覆盖。

## 依赖规则

保留原 P5 公开入口和测试替身，不添加真实模型调用。

## 数据与权限

合成 SEC 数据和临时运行目录；HTTP 在进程内验证。

## 测试与验收

执行 `python -m unittest discover -s tests/integration/p5 -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
