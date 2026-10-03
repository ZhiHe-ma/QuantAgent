# 使用说明

安装、新闻日报、插件及 API 的详细命令集中在这里，项目 README 只保留最短入口。验证范围见[兼容性矩阵](COMPATIBILITY_TEST_MATRIX.md)，开发规则见[架构规范](ARCHITECTURE.md)。历史记录保留原日期与版本。

## 按需阅读

[环境与新闻日报](#本地运行) · [离线观点跟踪](#离线观点跟踪) · [结果 API](#只读结果-api) · [Qlib](#qlib-因子研究插件) · [bt](#bt-组合回测插件)

## 本地运行

先获取代码或进入已有检出，下面的命令从仓库根执行：

```bash
git clone https://github.com/ZhiHe-ma/QuantAgent.git
cd QuantAgent
```

### 1. 准备 Python 环境

使用 **Python 3.12 或更新版本**。当前源码包含 Python 3.12 支持的 f-string 写法。

在项目根目录创建并激活虚拟环境：

```bash
python -m venv .venv
```

Linux / macOS：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = '1'
```

安装运行依赖：

```bash
python -m pip install requests yfinance python-dotenv
python -m pip install -r requirements.txt
```

SQLite 使用 Python 标准库中的 `sqlite3`。`requirements.txt` 锁定 Agent/Skill 清单运行时、P2 研究契约、Schema 校验和 P3a 只读 API 依赖；原有外部行情、RSS 和模型客户端尚未纳入同一锁文件，其实时可用性仍需在实际环境中核对。

### 2. 配置环境变量

在 `agent_engine.py` 所在目录创建 `.env`，将以下占位值替换为自己的配置：

```dotenv
DEEPSEEK_API_KEY=replace_with_your_api_key
DEEPSEEK_FAST_MODEL=replace_with_an_available_fast_model
DEEPSEEK_REASON_MODEL=replace_with_an_available_reasoning_model

DRY_RUN=true
FORCE_DAILY_RUN=false
ALLOW_MOCK_NEWS=false

# 需要真实发送消息时再配置企业微信机器人 Webhook。
# WECOM_WEBHOOK_URL=replace_with_your_webhook_url
```

模型名称应使用账号实际可调用的名称。源码中的默认名称只代表当前配置，不保证在所有账号和时间点均可用。

`.env`、日志、数据库和运行状态属于个人运行配置与数据，不应提交到仓库。

### 3. 先预览日报

保留 `.env` 中的 `DRY_RUN=true`：

```bash
python agent_engine.py --mode daily
```

试运行会读取已有数据，仍会访问行情与模型接口，模型调用可能产生费用。它会预览输出，但不会写入日报或状态、发送企业微信消息，也不会创建或连接审计数据库。

### 4. 持续采集与正式生成

确认配置后，将 `.env` 中的 `DRY_RUN` 改为 `false`。若需要消息推送，先填写 `WECOM_WEBHOOK_URL`。

在一个终端持续采集新闻：

```bash
python agent_engine.py --mode monitor
```

Monitor 会持续循环并调用模型；需要停止时使用 `Ctrl+C`。确认有新闻入池后，可以在另一个终端生成日报：

```bash
python agent_engine.py --mode daily
```

正式运行会在 `10_DailyNotes/` 下生成或更新业务文件。`deploy/` 提供每日定时执行和常驻监控的配置参考；08:00 的定时触发由 cron 等外部调度负责，Python 程序不会自行等待到该时刻。

`--mode weekly` 目前仅输出尚未实现的提示。

## 可选配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DRY_RUN` | `false` | 启用试运行，阻止业务写入与推送 |
| `FORCE_DAILY_RUN` | `false` | 允许当天日报再次执行 |
| `ALLOW_MOCK_NEWS` | `false` | 无真实新闻时是否允许使用代码中的示例新闻 |
| `MIN_STORE_WEIGHT` | `Medium` | 新闻进入当日池的最低评级 |
| `MAX_NEWS_PER_CYCLE` | `3` | 每轮交给模型处理的候选新闻数量上限 |
| `MAX_NEWS_AI_RETRIES` | `3` | 新闻处理失败的最大尝试次数，最小为 1 |
| `MAX_DAILY_FACTORS` | `8` | 日报使用的新闻因子数量上限 |
| `MAX_BUFFER_FACTORS` | `240` | 新闻池裁剪时使用的数量上限 |
| `MAX_RSS_ITEMS_PER_SOURCE` | `8` | 每个新闻源单轮读取的条目上限 |
| `RSS_TIMEOUT` | `15` | RSS 请求超时秒数 |
| `RSS_FEEDS` | 内置多个来源 | 自定义来源，格式为 `source::url\|source::url` |
| `QUANTAGENT_VERSION` | 未设置 | 可选的代码版本标识，用于审计记录 |

## 目录说明

| 文件或目录 | 主要用途 |
| --- | --- |
| `agent_engine.py` | 新闻采集与日报入口 |
| `quantagent_platform/` | 研究任务运行、结果记录与接口 |
| `recipes/` | 数据体检、观点跟踪等预设流程 |
| `docs/`、`tests/` | 详细文档与验证用例 |
| `deploy/` | 定时运行与部署配置参考 |
| `10_DailyNotes/`、`artifacts/` | 本地生成的日报、数据和研究结果 |

## 插件主机

插件把数据读取、分析和报告生成连接成预设流程，主要支持数据体检、离线观点跟踪、日报研究及实验性回测。普通用户可直接使用现成流程，无需逐个配置插件。

查看可用插件：

```bash
python -m quantagent_platform catalog
```

离线样本不调用外部模型；联网、数据库写入等操作需要显式授权。每次运行保存独立结果与记录。扩展方式见 [插件说明](QUANTAGENT_PLUGIN_CONTRACT.md) 和 [流程说明](QUANTAGENT_RECIPE_SPEC.md)。

## 受控 Agent 入口

Agent 是预设研究流程的统一入口，例如数据体检和离线观点跟踪。运行前会核对版本与权限，不会自行选择任意工具或执行交易。

查看可用入口：

```bash
python -m quantagent_platform agent-catalog
```

样本命令见[离线观点跟踪](#离线观点跟踪)。配置规则见 [Agent 说明](QUANTAGENT_AGENT_SKILL_SPEC.md)；已有的固定 SEC 复核流程不代表通用多 Agent 协作。

## 离线观点跟踪

P2 移植并重写了 Apache-2.0 的 `thesis-tracker` 方法，用严格研究契约替代企业持仓与交易动作字段。固定夹具只包含合成数据，不联网、不调用模型：

```bash
python -m quantagent_platform run-agent builtin.research-agent \
  --agent-version 1.0.0 \
  --source thesis-json \
  --input tests/fixtures/sample_thesis_review.json \
  --title "QuantAgent P2 Golden Thesis Report" \
  --output-dir artifacts/thesis-runs
```

Reader 只能读取显式授权的夹具；Analyst 只接收数据包且没有文件、网络或进程权限；Writer 只写当前运行目录。证据正文不会成为路径、插件绑定或权限，也不会被原样渲染到报告。相同证据再次应用到已更新状态时不新增版本；证据 ID 复用不同内容、哈希篡改、未来信息、标的不一致、额外能力或伪造状态都会失败关闭。

## 只读结果 API

P3a 先把既有运行结果暴露为本地、单用户、只读接口。Bearer token 至少 32 个字符，只从环境变量读取；`run_id` 只是资源标识，不是访问凭据。下面的服务默认只监听 loopback：

```powershell
$env:QUANTAGENT_API_BEARER_TOKEN = 'replace-with-at-least-32-random-characters'
python -m quantagent_platform serve-results `
  --run-root artifacts/thesis-runs `
  --subject local-owner
```

授权请求可读取 `GET /api/v1/runs/{run_id}` 和 `GET /api/v1/runs/{run_id}/report`。刷新或重复 GET 不会修改运行目录、创建新任务或调用模型；报告响应会重新校验运行状态、最终数据包与 Markdown 文件哈希。详细契约和错误语义见 [QUANTAGENT_READ_API.md](QUANTAGENT_READ_API.md)。

需要验证第一条写路径时，可改用 `serve-research` 显式登记本机 thesis 样本，并通过有幂等键的 `POST /api/v1/runs` 运行固定的离线研究 Agent。它不接受浏览器提供的路径或任意能力，也不是长任务队列或多用户 API；启动、契约和限制见 [QUANTAGENT_SUBMISSION_API.md](QUANTAGENT_SUBMISSION_API.md)。

同一 `serve-research` 服务还提供 `POST /api/v2/runs`、版本化状态查询和协作取消。它使用单进程有界工作线程，重启后不会自动重跑未完成任务；细节和限制见 [QUANTAGENT_TASK_LIFECYCLE_API.md](QUANTAGENT_TASK_LIFECYCLE_API.md)。

## 离线重放与结果回填

第二套套餐读取第一套运行保存的 `quantagent.signal_history.v1` 数据包，并使用明确提供的历史价格文件评价结果。预览模式不会修改数据库：

```bash
python -m quantagent_platform run recipes/offline_outcome_backfill.json \
  --source replay \
  --input artifacts/runs/<run-id>/01-load-signal-history.json \
  --allow-read-root . \
  --param prices_path=path/to/prices.json \
  --param target_database_path=10_DailyNotes/signal_audit.sqlite3 \
  --param apply_backfill=false \
  --param horizon_hours=[24,72,168] \
  --param max_observation_delay_hours=1 \
  --param neutral_band_decimal=0.002
```

确认使用数据库副本演练后，才把 `apply_backfill` 改为 `true`，并显式授权数据库所在目录：

```bash
  --allow-write-root 10_DailyNotes \
  --param apply_backfill=true
```

回填使用单个 SQLite 事务；相同结果重复运行保持幂等，不同结果与已存在记录冲突时整批回滚。评价要求来源显式提供带时区的 `decision_at`，不会用 `finalized_at` 冒充决策时间。当前只支持 Crypto 的 24/72/168 自然小时；方向命中不等于可交易收益。

## 日报、模型与报告插件

第三套套餐把日报上下文、分析模型和报告拆成可替换步骤。默认用固定分析文件离线验收，不调用模型：

```bash
python -m quantagent_platform run recipes/offline_daily_research.json \
  --source daily-json \
  --input tests/fixtures/sample_daily_context.json \
  --allow-read-root . \
  --param model_options='{"analysis_path":"tests/fixtures/sample_daily_analysis.txt"}' \
  --output-dir artifacts/daily-runs
```

将模型步骤绑定到实验性 DeepSeek 适配器时，必须同时显式开启在线模式和两项权限；API key 只从指定环境变量读取，不写入运行包：

```bash
python -m quantagent_platform run recipes/offline_daily_research.json \
  --source daily-json \
  --input path/to/daily_context.json \
  --bind model.daily_analysis=builtin.deepseek-daily-analysis \
  --param model_options='{"model":"deepseek-v4-pro","api_key_env":"DEEPSEEK_API_KEY","timeout_seconds":60}' \
  --online \
  --allow-permission network:https \
  --allow-permission environment:read-secret
```

现有 `agent_engine.py --mode daily` 仍是原有日报入口；它与插件报告共用同一提示词和渲染函数。本仓库仅用模拟传输验证 DeepSeek 适配器，未把真实外部调用标记为已验证。

## Qlib 因子研究插件

Qlib 作为重型依赖不安装到 QuantAgent 主环境。先创建独立虚拟环境并固定版本：

```powershell
python -m venv artifacts/qlib-env
.\artifacts\qlib-env\Scripts\python.exe -m pip install pyqlib==0.9.7
```

随后用固定本地 CSV 运行实验套餐。必须显式授权启动子进程，并把仓库根目录（包含 worker、隔离环境和样本）列入读取范围：

```powershell
python -m quantagent_platform run recipes/qlib_factor_research.json `
  --source qlib-csv `
  --input tests/fixtures/sample_qlib_factor.csv `
  --allow-read-root . `
  --allow-permission process:spawn `
  --param qlib_options='{"python_executable":"artifacts/qlib-env/Scripts/python.exe","timeout_seconds":120}' `
  --output-dir artifacts/qlib-runs
```

标准测试仅使用协议 worker，避免把 Qlib 的完整依赖树带入核心 CI。真实本机兼容测试需显式设置隔离解释器：

```powershell
$env:QUANTAGENT_QLIB_PYTHON = (Resolve-Path artifacts/qlib-env/Scripts/python.exe)
python -m unittest tests.test_qlib_plugins -v
```

真实测试会调用 `qlib.data.dataset.loader.StaticDataLoader`，并把 Python、pyqlib、pandas 精确版本及输入 SHA-256 写入结果。它不下载行情、不训练模型、不做回测，也不证明该结果具有收益或可交易性。

## bt 组合回测插件

首个回测引擎选择 [`bt`](https://github.com/pmorissette/bt)，固定版本 1.2.3。它使用 MIT 许可证、支持 Python 3.12，且直接面向组合权重和再平衡，适合当前因子研究阶段。选择记录及未选引擎的许可证和运行代价见 [BACKTEST_ENGINE_DECISION.md](BACKTEST_ENGINE_DECISION.md)。

`bt` 同样安装在独立环境中：

```powershell
python -m venv artifacts/bt-env
.\artifacts\bt-env\Scripts\python.exe -m pip install bt==1.2.3
```

用固定的时区时间、价格和信号面板运行套餐：

```powershell
python -m quantagent_platform run recipes/bt_portfolio_backtest.json `
  --source bt-csv `
  --input tests/fixtures/sample_bt_panel.csv `
  --allow-read-root . `
  --allow-permission process:spawn `
  --param backtest_options='{"python_executable":"artifacts/bt-env/Scripts/python.exe","price_semantics":"synthetic_close","execution_lag_bars":1,"top_n":1,"commission_bps":5,"slippage_bps":5,"periods_per_year":365}' `
  --output-dir artifacts/bt-runs
```

首版只做多，信号必须至少延迟一根 bar，并在报告中同时展示等权买入持有基线。手续费和滑点被合并为按成交金额计算的比例成本。真实兼容测试需显式指定隔离解释器：

```powershell
$env:QUANTAGENT_BT_PYTHON = (Resolve-Path artifacts/bt-env/Scripts/python.exe)
python -m unittest tests.test_bt_plugins -v
```

固定样本用于验证接口、时间顺序、成本和报告，不用于证明策略有效；小样本 CAGR 与 Sharpe 尤其不应当作收益证据。

## 当前边界

- 新闻清洗和去重主要依赖规则、标识及文本指纹，尚未实现语义去重。
- 日报质量依赖数据完整性和模型输出；模型给出的置信度尚未进行历史校准。
- 已支持显式历史价格文件的离线结果回填；自动取价、交易日口径和完整收益评估仍属于后续工作。
- 已支持 `bt` 固定样本组合回测，但尚未验证真实行情的复权、交易日、可成交性、容量、冲击、部分成交或订单生命周期。
- 数据体检和观点跟踪是固定的精选 Agent 组合。P3a 提供单用户只读结果接口；另一个显式启用的 `serve-research` 服务支持固定离线样本提交、状态查询和协作取消，不代表已提供 OpenStock 页面或多用户授权。P5 的固定 SEC 单跳复核不等于通用 Agent 协作；模型驱动选路、通用动态工具与预算控制、人工暂停恢复仍不属于现有能力。
- 第三方行情和新闻源可能出现访问限制、数据缺失或接口变化。
- 数据库设计文档含后续规划，功能是否完成以当前源码和测试为准。


## 本地恢复

Daily 自动继续同日未完成的原快照，不重新研究。查看：`python agent_engine.py --mode recover --action status`；指定任务追加 `--run-id <编号>`。`--action retry --run-id <编号>` 只补缺失步骤；已完成可选消息原先未配置时，仅这次显式请求可首次绑定当前渠道。

消息 unknown 先人工核对：`--action confirm-sent` 只登记收到；`--action confirm-not-sent` 只登记未收到，之后仍须明确 retry 才补送。它们不能撤回已发送内容。渠道变动停止发送，恢复原渠道再试。

`--action abandon --run-id <编号> --reason "用户终止原因"` 保留历史且停止恢复；未完成不伪报成功。状态、确认和终止无需研究引擎；DRY_RUN=true 下恢复动作只预览，不创建目录、库、锁或事件。历史半成品无完整快照时需人工处理，不能从新行情补造历史。
