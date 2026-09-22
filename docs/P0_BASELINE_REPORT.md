# P0 Baseline Report

验证时间：2026-09-22（Asia/Shanghai）

证据等级：`offline_fixture`；可选真实依赖测试为 `skipped`

## 锁定对象

| 对象 | 精确值 |
| --- | --- |
| GitHub 仓库 | `ZhiHe-ma/QuantAgent` |
| 基线 commit | `12407081cb882ae526180145237f32093f83dffc` |
| 基线 tree | `bb614fd541ea72b3fa1ccafdcdc1498c7f78c4e1` |
| 分支 | `main` |
| 本地平台 | Windows 11 `10.0.22631` x64 |
| Python | CPython `3.12.8`，MSC v.1942 64 bit |
| 编码模式 | `PYTHONUTF8=1` |
| 测试命令 | `python -m unittest discover -s tests -v` |

基线中的核心离线测试只使用 Python 标准库。P0 分支新增 `requirements-test.txt` 锁定的测试依赖，其中直接验证器为 `jsonschema[format-nongpl]==4.25.1`；它只用于 Schema 元校验、示例验证和日期/URI format checker，不是核心运行依赖。Qlib 与 bt 是可选隔离依赖，不安装进核心环境；其真实测试分别要求 `QUANTAGENT_QLIB_PYTHON` 和 `QUANTAGENT_BT_PYTHON` 指向已固定的专用解释器。

## 结果

- 运行 81 个测试，其中 79 个通过、0 个失败、2 个跳过。
- 两个跳过项为 `test_real_pyqlib_static_loader` 和 `test_real_bt_engine`；本次未设置相应解释器，因此不能把历史真实依赖记录写成本次复验结果。
- 已覆盖当前离线数据包、路径/权限预检、失败关闭、日报回放、结果回填、Qlib/bt 协议替身、Signal Audit 和幂等行为。
- 未覆盖真实 DeepSeek、在线行情/新闻、真实 Qlib/bt 依赖、Agent/Skill Runtime、Tool Broker、Typed Handoff、OpenStock API/UI、操作系统级沙箱和收益有效性。

## 固定夹具哈希

| 文件 | SHA-256 |
| --- | --- |
| `tests/fixtures/sample_signals.json` | `ba47d50b87e527477d0ec190b70e3154f6b36c89575f1fbf4a10eac1f01dca7b` |
| `tests/fixtures/sample_prices.json` | `8022bba1d1e0e847418609cba1f23308c29ade05247198de65ed1d7f2ea772bb` |
| `tests/fixtures/sample_daily_context.json` | `c40daecda65489aaa375a8ed604769e7903df394e81ca575f7e7ebca071dbb33` |
| `tests/fixtures/sample_daily_analysis.txt` | `01f9da5c1ea18807fd48c65505e0772a4a5fbfd265df9cfb6030b8d1619af6ec` |
| `tests/fixtures/sample_qlib_factor.csv` | `eae686cdc429fe06f87a9046a185f3babc17c5f4a8aca1e8f527457a13b94a99` |
| `tests/fixtures/sample_bt_panel.csv` | `e12f2d4a238f9e63df043e174ee1cfe8f0af7c7e1b643bae263311719f0bfed4` |

## P0 新增规范状态

AgentManifest、SkillManifest、研究契约、细粒度权限、审查/预算和交接字段在本阶段仅具有 `static` 证据。Schema 文件采用 JSON Schema Draft 2020-12，并由固定的 `jsonschema` 4.25.1 完成 Schema 自检、结构示例、未知字段、版本范围和首版非空 `callable_agents` 拒绝测试。P1 仍需补真实加载器、能力/权限交集和跨目录引用行为测试。

P0 变更后的完整回归共运行 86 个测试，其中 84 个通过、0 个失败、2 个跳过；新增 5 个规范测试全部通过，原有两个真实依赖跳过项保持不变。
