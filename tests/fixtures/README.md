# 固定静态样本

## 职责与边界

保存原 JSON、CSV、TXT 输入及预期数据；可执行 worker 归入 support/fakes。

## 文件导航

- [sample_bt_panel.csv](sample_bt_panel.csv)：原固定样本。
- [sample_daily_analysis.txt](sample_daily_analysis.txt)：原固定样本。
- [sample_daily_context.json](sample_daily_context.json)：原固定样本。
- [sample_prices.json](sample_prices.json)：原固定样本。
- [sample_qlib_factor.csv](sample_qlib_factor.csv)：原固定样本。
- [sample_signal_packet.json](sample_signal_packet.json)：原固定样本。
- [sample_signals.json](sample_signals.json)：原固定样本。
- [sample_thesis_review.json](sample_thesis_review.json)：原固定样本。
- [sample_thesis_review_expected.json](sample_thesis_review_expected.json)：原固定样本。
- [p5_review_compatibility.json](p5_review_compatibility.json)：D002 前提交的合成 SEC 样本经原离线 P5 生成的固定回证、报告哈希和账本预期，保留来源提交与时间。比较排除每次变化的链 ID、父运行 ID 和交接哈希；这些动态字段仍由原交接、状态与哈希测试验证。
- [api_route_compatibility.json](api_route_compatibility.json)：从 D003 前 `f02a0e2bdf6dacf1b60222386e2b2b5c80e22d5b` 捕获的 HTTP schema、错误与响应预期；仅含合成数据，不含凭据或临时路径。

全局目录见 [测试导航](../README.md)。

## 对外接口

文件只提供静态输入及预期数据，测试按原格式读取，不能作为生产配置。

## 依赖规则

由测试通过共享 ROOT 定位读取，不直接执行样本内容。

## 数据与权限

原合成/固定样本字节、编码和数值不变；没有私人账户资料。

## 测试与验收

执行 `python -m unittest discover -s tests -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

新增 P5 样本由 [边界集成](../integration/p5/test_p5_boundaries.py) 验证，捕获过程及重构验收见 [D002](../../docs/features/d002-p5-boundaries.md)。

HTTP 样本由 [API 组装测试](../integration/test_api_composition.py) 比较，捕获环境为 FastAPI 0.141.1 / Pydantic 2.13.5；来源、哈希与实际验收见 [D003](../../docs/features/d003-api-composition.md)。依赖升级若改变 schema，应核对原因和契约后重新建立明确版本的预期，不能为通过测试直接覆盖旧样本。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
