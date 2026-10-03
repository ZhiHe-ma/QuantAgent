# D004：SEC 响应契约与客户端分离

```json
{
  "branch": "refactor/d004-sec-contracts",
  "base_commit": "722550fe26c39b45725935052b04114c71b107e1",
  "sec_contract_commit": "a79f1a84b2bfc08d61787e61aeb73a4c0236806d",
  "tested_commit": "331ac4630d9363ae120a58d74aa4e32625d4c72a",
  "components": ["sec-contracts", "sec-response-contracts", "sec-source-identities", "sec-adapter", "runner", "architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "仅登记新的纯响应契约并删除实际消除的 D004 引用；检查器、规则及 CI 命令不变。"
  }
}
```

## 目标与非目标

执行[整改清单](../architecture/remediation.md)的 D004，移除 `sec_contracts → sec_client`。规范以[架构](../ARCHITECTURE.md)和[文件归属](../DEVELOPMENT_TESTING.md)为准；不整改 D005–D006，不实现学习或修改真实 SEC 获取行为。完整回归另复现原 Windows 并发提交的文件替换失败，作为 Task 2 单独修复和提交，保持 HTTP/数据契约。

## 涉及模块

新增 `sec_response_contracts.py`，仅拥有不可变响应、8 MiB 上限和固定来源 URL；原 `sec_contracts` 负责标准化校验，`sec_client` 负责获取，`sec_source_identities` 保留证据文件名和原 URL 别名。新增能力按实际职责登记，不调整现有模块层级或所属方。

## 接口或数据变化

保留 `SecResponse(kind: str, cik: str, url: str, raw: bytes, sha256: str, retrieved_at: str)` 的六项字段、位置参数、`frozen=True, repr=False`，以及旧客户端/标准化模块的响应和常量导入。`normalize_sample(responses)`、`validate_sec_packet(packet)` 和 `fetch_sample(...)` 的签名、方法体、错误、哈希、时间、来源及获取上限保持；响应 DTO 不额外执行准入校验。

## 新增依赖

新增纯契约只依赖标准库 dataclass；三个原能力仅添加指向此新能力的精确允许项，原能力两两允许关系不变。URL 定义移入新契约，旧来源模块保留别名，避免通过额外转发层隐藏引用；不新增 SDK、豁免或放宽门禁。

同步原 P5 静态用例的按模块白名单：P5 ports 仍仅允许 Packet，SEC 来源别名仅允许新响应契约；新增静态用例验证新契约不引用本地能力或 IO。不是对所有模块统一扩大允许集。

## 测试证据

环境：2026-10-03，Windows、仓库外 Python 3.12.8、原 `.venv/Lib/site-packages`；UTF-8 输出。基线 SEC 命令 `python -m unittest tests.test_sec_client tests.contract.sec.test_sec_contracts tests.unit.research.test_sec_analysis tests.integration.sec.test_sec_workflow -v`：22 项通过，0.165 秒。原始记录在本地忽略的 `artifacts/architecture/d004-sec-contracts/`。

实际解释器 `C:\Users\yj\AppData\Local\Programs\Python\Python312\python.exe`，从仓库根设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`PYTHONPATH=<仓库>/.venv/Lib/site-packages`；门禁 PATH 包含 `D:\Git\cmd`。

| 验证 | 实际结果 |
| --- | --- |
| SEC 边界与回归 | 新 4 项及原 SEC 22 项：26/26，1.037 秒；修正原按模块白名单后边界 6/6，1.049 秒 |
| Windows RED → GREEN | 原写入真实占用恢复及模拟重试按预期失败；`python -m unittest tests.unit.test_runner_atomic_write tests.test_submission_api.SubmissionApiTests.test_concurrent_same_key_executes_at_most_once -v`：5/5，0.316 秒；真实 Windows 句柄已验证 |
| 并发诊断 | 原行为第 16 轮复现 WinError 5；修复后原四路同键提交连续 20 轮全部得到 `[200,200,200,201]`，未跳过并发用例 |
| 完整离线 | `python -m unittest discover -s tests -v`：323 项、0 失败、7 跳过，63.950 秒 |
| 兼容与门禁 | `python artifacts/architecture/d004-sec-contracts/verify_compatibility.py`：81 个原资产、24 项原 SEC 定义及除已说明写入 helper 外的原 runner AST 保持，共 25 项核对；2,401 个原允许关系、原 Packet 和别名保持。完整门禁通过，53 个模块、9 条精确存量、无循环，Import Linter 返回 0 |
| 独立只读审查 | `722550f..762dfc5`：Critical/Important/Minor 均无；审查者实际执行下述 11 项，全部通过、无跳过，1.347 秒 |

保留前两次完整日志：319 项分别因旧边界白名单及已复现 Windows 替换失败而失败，修复后完整回归通过。7 项跳过为原真实 bt/Qlib、私有 P4、三项 Windows 链接，以及当前临时目录卷未启用 8.3 文件名的短路径用例；最终完整回归源码和测试对应 `tested_commit`，后续仅补录文档。

审查者在同一解释器和依赖环境使用 `PYTHONDONTWRITEBYTECODE=1` 执行 `python -B -m unittest tests.architecture.test_sec_boundaries tests.architecture.test_p5_boundaries tests.contract.sec.test_sec_response_contracts tests.unit.test_runner_atomic_write tests.test_submission_api.SubmissionApiTests.test_concurrent_same_key_executes_at_most_once -v`，退出码 0。原始审查工具输出 `chunk_id=3e0dba`，报告在上述本地证据目录的 `final-review.md`；7 个执行工作文件已复制到 `execution/` 并逐个验证 SHA256。

### Task 1: 提取最小 SEC 响应契约

- [x] 捕获原源码定义、固定资产哈希和冻结时钟的标准化 Packet；保留原用户删除。
- [x] 写静态边界、旧类型身份及不可变字段、独立契约重载进程、双端读取上限测试。
- [x] 运行 `python -m unittest tests.architecture.test_sec_boundaries tests.contract.sec.test_sec_response_contracts -v`。Expected: 缺少纯契约及客户端耦合导致预期断言失败；原上限特征用例通过。
- [x] 移动原响应/常量定义、保留旧别名并登记新能力；原函数体不改。Expected: 新增 4 项加原 SEC 22 项通过（实测 26/26，1.037 秒）。
- [x] 静态及 AST 核对原关系和行为；仅移除 D004 的精确引用，更新所属 README。Expected: 52→53 个模块、10→9 条存量、无循环或新增违规；实测 82 个原资产、24 项 AST、2,401 个原允许关系及固定时钟 Packet 保持。
- [x] `python -m tools.architecture --base-ref 722550fe26c39b45725935052b04114c71b107e1 --branch refactor/d004-sec-contracts --report artifacts/architecture/d004-sec-contracts/gate.json`：门禁通过，Import Linter 返回 0。全量回归的已复现 Windows 写入问题转 Task 2。
- [x] 单独本地提交：首个 JSON 的 `sec_contract_commit`。

### Task 2: Windows 原子状态写入回归

- [x] 新增 `tests/unit/test_runner_atomic_write.py`：真实 Windows 读句柄占用恢复、模拟 WinError 5/32 有限重试、永久拒绝保留旧字节、其他错误及非 Windows 不重试。Expected: 原写入在占用恢复/重试用例中按预期失败。
- [x] 仅调整 `runner._atomic_json_write()` 的 replace：Windows 5/32 最多 5 次，失败间隔 10/20/30/40 ms；其他错误立即沿用原异常。Expected: 新测试通过，永久拒绝仍抛异常且旧目标字节不变。
- [x] 复跑原四路同键提交及全套 `python -m unittest discover -s tests -v`，记录每次失败与跳过。Expected: 完整离线通过；不跳过并发用例、不声称永久权限错误被修复。
- [x] 更新 README 和验收，单独提交；最后运行上面的完整门禁作为 task-done 验证。
- [x] 一次独立只读审查整个分支，归档执行记录，保留本地分支和工作树。

Review focus: 旧 SecResponse 导入及 isinstance 身份；既有启动组装后的独立契约重载不依赖客户端/可选 SDK；客户端和标准化共用原 8 MiB 上限与四个固定 URL；frozen/repr 与原 SHA/时间/严格 JSON 语义；Windows 原子替换只有限处理 5/32、失败保持旧字节、非 Windows及其他错误行为；P5、CLI/HTTP 和固定配方间接兼容，原允许关系保持。

## 回滚方式

回退本批提交恢复原定义、导入、登记与精确基线。没有数据迁移，不改写既有运行目录、Packet 或账本；用户已有项目方案删除保持原样。

## 遗留问题

当前仍部分符合，剩余问题以精确基线为准。Linux/远端 CI、真实 SEC、私有 P4、真实 bt/Qlib、部署和生产未运行，Windows 链接用例按实际环境记录。旧公开导入与 JSON/Packet 已按上述证据核对；私有 monkeypatch、类模块元数据及跨版本 pickle 不作额外兼容承诺。原子写入 helper 仍需调用方协调写者，永久失败可保留原有 `.tmp`；本批不扩展为任意多写者协调器。
