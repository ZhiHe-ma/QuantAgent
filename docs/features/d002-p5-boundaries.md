# D002：P5 校验、执行与存储边界

```json
{
  "branch": "refactor/d002-p5-boundaries",
  "base_commit": "7e6033bf337f5abbc9baf938e0d7023b650440dc",
  "tested_commit": "992f5a25efe8571de3c80261b8ea5b4fdc79e97e",
  "components": ["p5-domain", "p5-ports", "p5-storage", "p5-composition", "p5-adapter", "p5-workflow", "sec-source-identities", "sec-adapter", "compatibility-exports", "architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "仅精确登记新增 ports、身份常量与组装能力，并删除已消除的引用；检查器接口、行为及命令不变。"
  }
}
```

## 目标与非目标

执行 [整改清单](../architecture/remediation.md) 的 D002，消除其剩余 12 条引用问题。P5 交接校验只使用公开数据契约与抽象接口；文件、批准源和 SQLite 由所属存储适配器处理，工作流负责固定父子路由。保留授权、预算、取消、幂等、哈希与恢复语义；不实现学习，不整改 D003–D006。

## 涉及模块

P5 ports 保存最小数据视图、证据对象、错误与存储接口；p5-storage 提供原有安全读取、账本和控制器锁实现；p5-composition 在包启动时注入它。handoff/review 不引用 Agent、runner 或具体存储，plugins/coordinator/worker 不引用具体存储或其私有成员。SEC 固定来源身份移入纯契约并保留原客户端导入路径，SEC 响应类型的 D004 问题另批处理。

## 接口或数据变化

保留原 P5 公开导入路径、函数和默认构造，证据 dataclass 及错误由契约拥有、旧入口继续导出。协调器可显式注入存储接口；默认由受控启动入口组装。JSON、配方、manifest、策略、schema、SQL、CLI/HTTP 和消息格式不变，不扩张权限或数据归属。

## 新增依赖

新增 P5 ports、存储实现与启动组装文件，以及 SEC 身份常量文件；登记指向新增契约/组装能力的精确允许项。没有新增第三方库，不放宽既有能力之间的关系，不增加豁免、动态加载或反向导入。

## 测试证据

环境：2026-10-02，Windows 11、仓库外 Python 3.12.8、原 `.venv/Lib/site-packages`、UTF-8 输出。基线为首个 JSON 的提交；本批原始日志、静态图、兼容样本与审查记录保留在忽略的 `artifacts/architecture/d002-p5-boundaries/`。

所有 Python 命令从仓库根执行，使用 `C:/Users/yj/AppData/Local/Programs/Python/Python312/python.exe`；设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`PYTHONPATH=<仓库根>/.venv/Lib/site-packages`，门禁 PATH 加入 `D:/Git/cmd`。

实施前 `python -m unittest discover -s tests -v`：295 项，0 失败，原 6 项跳过。新增 10 项反例先得到 3 失败、6 错误及 1 项原输出特征通过，实施后 10 项全部通过。先运行的全套发现原启动矩阵错误包含新增能力；固定 D001 前 42 项能力后，该回归单独通过，仍检查原 1,764 组关系，没有修改门禁规则。

兼容核对命令：`python artifacts/architecture/d002-p5-boundaries/verify_compatibility.py`。实际保持原 12 项包根导出、29 个默认插件、65 个未改产品/配置/旧样本文件哈希、全部 1,849 组本批前能力关系；账本类与 SQL、安全读取、pin 校验、复核函数、控制器锁、原子写入和进程监督的 AST 与原版一致。固定合成回证及报告哈希来自基线提交，经真实离线 worker 对比；不是私人 P4 或真实 SEC 验收。

最终完整命令 `python -m unittest discover -s tests -v`：305 项，0 失败，6 项原有跳过，66.381 秒。`python -m tools.architecture --base-ref 7e6033bf337f5abbc9baf938e0d7023b650440dc --branch refactor/d002-p5-boundaries --report artifacts/architecture/d002-p5-boundaries/gate.json`：通过，47 个源码模块、15 条精确存量问题、一组原 API 循环，Import Linter 返回 0；仅移除实际消除的 D002 12 条。`git diff --check`：通过。

源码及测试验收版本为首个 JSON 的 `tested_commit`；后续证据说明提交不改变这份已验收代码。原项目方案删除未纳入提交。

Linux/CI、真实服务、私有 P4 与生产尚未运行；真实 bt/Qlib 开关和三项 Windows 链接权限限制仍属原跳过范围。只处理公共研究及本机运行审计，不验证 OpenStock 私有账户写入、学习或交易。

### Task 1: 分离 P5 规则与具体存储

1. 核对基线、保留原用户删除，记录公开入口、目录、配置/样本哈希和固定合成 P5 的回证输出。
2. 新增反例，观察校验层/工作流对具体存储的依赖与纯契约缺失导致失败。
3. 提取纯 P5 数据、严格 JSON 与标识符规则；通过结构化视图移除 TYPE_CHECKING 反向引用。
4. 存储实现承接原安全读取、账本、控制器锁及原子写入；启动组装注入，业务与执行代码依赖 ports。
5. 固定 SEC 身份常量归纯契约，原导入路径兼容。登记新增能力，不修改旧层级、放宽检查或新增豁免。
6. 回归公开 Python、CLI/HTTP、固定配方、授权/预算、取消、哈希、幂等、进程失败与恢复；完整离线测试通过后缩减实际消除的基线。
7. 同步模块 README 和本节验收、运行门禁、本地提交，然后进行一次独立审查。

Expected: D002 的 12 条全部消除，无新增违规或循环，门禁及 Import Linter 通过；其他未整改问题继续明确登记。原固定输出与配置兼容，原跳过范围保留。

Review focus: 纯契约不含具体 IO 或工作流引用；默认启动及子进程注入顺序；错误类型、原导入、固定哈希兼容；读取边界、链接/替换检查、账本幂等/恢复与控制器锁；不把数据读取和规则更新授权混为一谈。

## 回滚方式

回退本批提交恢复原引用与精确基线；不迁移 SQL 或改写现有研究/账本数据。原用户未提交的项目方案删除不纳入本批提交。

## 遗留问题

D003 的 API 循环、D004 的具体 SEC 响应依赖、D005 的跨适配器共享、D006 的旧引擎依赖继续分批整改；清零并完成所需验收前仍部分符合。学习及 OpenStock 私有数据更新仍由后续业务独立验证。
