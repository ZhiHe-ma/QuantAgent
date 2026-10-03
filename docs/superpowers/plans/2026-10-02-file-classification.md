# QuantAgent 首批文件分类实施计划

对应 [设计](../specs/2026-10-02-file-classification-design.md)。这是已批准跨应用计划中的 QuantAgent 子集；仓库外私人分类及另一应用的工具提交由本地验收记录追踪，不复制私人路径、日志或现场配置。

## 全局约束

基线 `3006e57069b7da92caf0f869c307bd4b0e7a1ea4`，实施分支 `feature/file-classification`。原分支和工作树保留；运行时代码、固定配置、允许依赖和存量豁免不变。不推送、合并、部署或实现学习业务。

## Task 1: 基线

保存工作树状态、原用例清单、文档门禁和原文件 SHA-256。基线全套实际 279 项、0 失败、6 跳过；42 条存量问题、Import Linter 退出 0。原始产物只保留在忽略目录。

## Task 2: 规范导航

先建立 [实际源分支说明](../../features/file-classification.md)，再写 [归属规范](../../DEVELOPMENT_TESTING.md)，登记文档资产并同步 [测试导航](../../../tests/README.md)。自动检查本地引用与架构门禁；规范提交与后续测试整理分开。

## Task 3: 测试支持

先写并运行三个失败路径用例，再实现 `tests/support/paths.py` 的 `repository_root(start: Path) -> Path` 与 `ROOT`。从指定文件所在目录向上寻找最近同时含 `agent_engine.py` 文件及 `quantagent_platform/`、`recipes/`、`tests/` 目录的根；没有则 `FileNotFoundError`，不依赖 cwd。

将 `ISSUERS`、`make_payloads()`、`make_responses(payloads=None, *, retrieved_at=None)` 从 SEC 测试抽到 `tests/support/sec_samples.py`，保留算法、字节、哈希和默认时间语义。更新九个调用者，不让测试用例成为共享库。更新原路径深度定位和两个 fake worker 路径。

## Task 4: 六文件试点

| 原路径 | 目标路径 |
| --- | --- |
| `tests/test_sec_analysis.py` | `tests/unit/research/test_sec_analysis.py` |
| `tests/test_sec_contracts.py` | `tests/contract/sec/test_sec_contracts.py` |
| `tests/test_schema.py` | `tests/contract/platform/test_schema.py` |
| `tests/test_sec_workflow.py` | `tests/integration/sec/test_sec_workflow.py` |
| `tests/test_p5_cli_api.py` | `tests/integration/p5/test_p5_cli_api.py` |
| `tests/test_signal_audit_integration.py` | `tests/integration/audit/test_signal_audit_integration.py` |

两个 `fake_*_worker.py` 从 fixtures 移到 `tests/support/fakes/`，内容字节不改。补包标记、分类说明、七项 README 和登记；其他测试原位，静态 JSON/CSV/TXT 不动。

## Task 5: 验收与审查

用与基线相同的 `unittest.defaultTestLoader.discover('tests')` 展平唯一 ID；只按六项模块前缀映射，原 279 项必须全部保留且无重复，新三个路径测试单列，预期 282 项。主命令与 unit/contract/integration 子目录各运行非零数量；bt/Qlib 离线协议通过，真实后端按原开关跳过。

实际执行补充：首轮 282 项通过。独立审查复现原单文件入口被新导入顺序破坏，增加一项含 12 个启动子例的回归测试（六平铺、六分类）；RED→GREEN 修复后最终全套 283 项、0 失败、6 跳过，58.508 秒，原 279 项仍完整对应。平铺用例的两种启动方式导入同一共享路径源，分类入口引导按祖先查找共享支持，资源定位仍使用四标记规则。

运行 `python -m tools.architecture --base-ref 3006e57069b7da92caf0f869c307bd4b0e7a1ea4 --branch feature/file-classification`，预期 PARTIAL_COMPLIANCE、42 条存量问题、Import Linter 退出 0。记录环境、命令、完整提交、结果和未测范围；独立审查全差异，重要发现先失败复现再修复。

## Review Focus

确认原用例没有遗漏或重复；子目录与 cwd 不破坏文件定位；fake worker 权限和失败关闭行为保持；静态样本及运行时原字节未改；各分支能力和本地证据不混为已发布版本。
