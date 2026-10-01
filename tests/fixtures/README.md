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

全局目录见 [测试导航](../README.md)。

## 对外接口

文件只提供静态输入及预期数据，测试按原格式读取，不能作为生产配置。

## 依赖规则

由测试通过共享 ROOT 定位读取，不直接执行样本内容。

## 数据与权限

原合成/固定样本字节、编码和数值不变；没有私人账户资料。

## 测试与验收

执行 `python -m unittest discover -s tests -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
