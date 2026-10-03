# 审计存储契约

## 职责与边界

验证正式审计 SQL 的约束、迁移、数据一致性；不是修改数据库设计。

## 文件导航

- [test_schema.py](test_schema.py)：SQL schema 用例。

全局目录见 [测试导航](../../README.md)。

## 对外接口

保持原 unittest TestCase、测试方法、断言与失败条件；发现命令从仓库根执行。直接运行脚本时按文件祖先引导所属包，再用共享 ROOT 验证仓库标记；--help 启动由专项回归覆盖。

## 依赖规则

使用标准库 sqlite3 与 tests.support.paths 定位正式 SQL，不改迁移内容。

## 数据与权限

每个用例使用临时 SQLite，读取 sql/001_signal_audit.sql；测试结束清理。

## 测试与验收

执行 `python -m unittest discover -s tests/contract/platform -t . -v`；实际数量、用例映射、环境与跳过见 [分支说明](../../../docs/features/file-classification.md)。离线替身通过不构成真实后端或生产验收。

## 已知限制

本批是分类试点；其他平铺用例仍按测试导航保留。当前架构部分符合，存量问题不因目录整理消除。
