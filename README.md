# QuantAgent

QuantAgent 是一台可以插“功能卡带”的量化主机：以小核心连接数据、校验、研究、回测与报告能力，并保存可追溯的运行记录。现有市场信息采集与日报流程继续保留，新增能力通过受控插件和经过验证的配方逐步接入。

项目起点是个人每天收集市场信息时遇到的重复工作：多个来源需要分别查看，相同新闻反复出现，前一天的判断也容易缺少后续核对。QuantAgent 将采集、筛选、汇总和记录整理为一套可运行的流程。

当前已落地历史数据体检、结果回填、日报研究和离线观点跟踪套餐，并保留原有信息整理与纸面观察能力。P1/P2 的精选 Agent 只能选择固定版本的 Skill/Recipe，并复用原有 `RecipeRunner`、权限预检和运行审计；`thesis-tracker` 可把旧观点、支持/反对证据和失效条件组织成可重放的确定性修订。P3a 新增带 Bearer 认证的本地只读结果 API，用于读取既有运行摘要和完整性校验后的 Markdown 报告；它不会创建或重跑任务。Qlib 和 `bt` 已有受控的实验适配器。自动交易、真实行情回测、仓位管理、多来源对账、完整周报、模型驱动 Agent、Qlib 模型训练、OpenStock 页面及任务提交等仍未接入，不能视为已实现或已验证。

## 已有功能

| 环节 | 当前实现 |
| --- | --- |
| 新闻采集 | 读取多个 RSS / Atom 来源，清洗正文并统一时间、来源和标识字段 |
| 去重筛选 | 结合新闻标识、内容指纹和历史处理记录去重，按重要程度筛选入池 |
| 失败处理 | 对新闻处理失败进行有限次数重试，达到上限后记录并隔离 |
| 行情汇总 | 尝试获取 BTC 价格与涨跌幅、恐慌贪婪指数、标普 500 和 VIX 数据；缺失项保留缺失状态 |
| 日报生成 | 结合行情、当日新闻及历史摘要调用 DeepSeek，生成 Markdown 日报 |
| 跨日记忆 | 保存最近一次摘要及最多七条历史摘要，为后续日报提供上下文 |
| 消息交付 | 通过企业微信机器人发送摘要，并记录接口确认的交付结果 |
| 信号审计 | 使用 SQLite 保存已完成的运行、判断、输入因子和交付状态，便于后续查询 |
| 试运行 | 预览日报和审计内容，阻止业务文件写入、消息推送及审计数据库连接 |

## 处理流程

项目有两个主要运行入口：

- **Monitor**：持续采集新闻，完成清洗、去重、模型评级和规则校准，将符合条件的信息写入当日新闻池。
- **Daily**：读取当日新闻池和历史摘要，获取行情并生成日报，然后依次保存日报、尝试推送、生成并保存记忆摘要，最后记录信号审计。

Daily 本身不负责 RSS 新闻采集。首次直接运行 Daily 时，新闻池可能为空；如需包含当日新闻，应先让 Monitor 完成采集。

同日已经生成日报且保存了当天记忆时，常规 Daily 会跳过重复执行。`FORCE_DAILY_RUN=true` 可以显式重跑，可能重新调用模型、覆盖当天 Markdown 日报并再次推送；成功保存的审计运行会保留历史记录。

## 目录说明

| 文件或目录 | 用途 |
| --- | --- |
| `agent_engine.py` | 新闻与行情采集、筛选、日报、记忆和消息交付主流程 |
| `signal_audit.py` | SQLite 迁移、记录校验、事务写入与查询 |
| `sql/001_signal_audit.sql` | 信号审计数据库结构 |
| `tests/` | 试运行、重复执行、异常隔离及审计存储测试 |
| `docs/P1_SIGNAL_AUDIT_SCHEMA.md` | 审计模块的设计说明与阶段边界，含后续规划 |
| `quantagent_platform/` | 最小插件主机、版本化数据包、权限预检、配方运行器与只读结果 API |
| `plugin_catalog/catalog.json` | 首批允许加载的精选插件及精确版本 |
| `agent_catalog/catalog.json` | P1/P2 允许加载的 Agent、Skill 和 Recipe 精确版本及 SHA-256 |
| `THIRD_PARTY_LICENSES/` | 移植 Skill 的完整第三方许可证副本 |
| `recipes/historical_data_health.json` | 历史数据体检套餐；数据入口可按配置替换 |
| `recipes/offline_outcome_backfill.json` | 离线重放、结果评价及可选事务回填套餐 |
| `recipes/offline_daily_research.json` | 日报上下文、分析模型和报告生成套餐 |
| `recipes/thesis_tracker.json` | 旧观点、离线证据、确定性状态修订和观点报告套餐 |
| `docs/QUANTAGENT_*.md` | 数据、插件、配方、Agent/Skill 和受控服务 API 规范 |
| `schemas/` | Agent/Skill、P2 研究对象、运行摘要与任务状态的 Draft 2020-12 Schema |
| `docs/QUANTAGENT_READ_API.md` | P3a 本地只读 API 的端点、认证、完整性检查和部署边界 |
| `docs/QUANTAGENT_SUBMISSION_API.md` | P3c 首步：显式启用的本机离线样本提交、幂等和未实现边界 |
| `docs/QUANTAGENT_TASK_LIFECYCLE_API.md` | P3e 本机异步状态与协作取消；重启后不自动恢复 |
| `docs/COMPATIBILITY_*.md` | 兼容声明规则和实测矩阵 |
| `docs/P0_BASELINE_REPORT.md` | 锁定提交、环境、测试结果、跳过项和固定夹具哈希 |
| `deploy/` | cron 与 systemd 配置参考，使用前需修改运行用户和安装路径 |
| `10_DailyNotes/` | 运行后产生的日报、新闻池、状态与数据库；不纳入版本控制 |

## 插件主机

已验证套餐默认使用 Python 标准库且不联网；DeepSeek 适配器为显式选用的实验插件：

| 插件 | 能力 | 权限 |
| --- | --- | --- |
| `builtin.sqlite-signal-source` | 以 SQLite `mode=ro` 读取 `daily_signals` | 读文件 |
| `builtin.json-signal-source` | 读取 JSON 历史快照 | 读文件 |
| `builtin.signal-data-quality` | 检查必填字段、重复 ID 和时区时间 | 无 |
| `builtin.markdown-quality-report` | 生成带范围说明的体检报告 | 写本次运行目录 |
| `builtin.packet-replay-source` | 校验并离线重放已保存的信号包 | 读文件 |
| `builtin.signal-outcome-evaluator` | 用固定价格文件评价 24/72/168 小时结果 | 读文件 |
| `builtin.sqlite-outcome-writer` | 预览或事务回填 `signal_outcomes` | 读写显式授权的数据库 |
| `builtin.markdown-outcome-report` | 生成结果回填及不可评价说明 | 写本次运行目录 |
| `builtin.json-daily-context-source` | 读取并校验日报研究上下文 | 读文件 |
| `builtin.replay-daily-analysis` | 离线重放固定模型分析 | 读文件 |
| `builtin.deepseek-daily-analysis` | 可替换的 DeepSeek 分析模型（实验） | 联网、读取环境密钥 |
| `builtin.markdown-daily-report` | 生成与原生产入口同形的日报 | 写本次运行目录 |
| `builtin.qlib-factor-research` | 在显式指定的隔离 Python 中用 Qlib 加载固定因子样本并计算 IC | 读文件、启动进程 |
| `builtin.markdown-factor-research-report` | 报告 Qlib 环境、输入哈希、指标和验证边界 | 写本次运行目录 |
| `builtin.bt-portfolio-backtest` | 在隔离 Python 中运行带信号延迟、成本和基线的 `bt` 组合回测 | 读文件、启动进程 |
| `builtin.markdown-backtest-report` | 报告回测假设、结果、基线、版本和边界 | 写本次运行目录 |
| `builtin.json-thesis-review-source` | 读取并校验离线观点、证据和 Point-in-Time 夹具 | 读文件 |
| `builtin.deterministic-thesis-tracker` | 去重证据并更新 claim、失效条件和研究状态 | 无 |
| `builtin.markdown-thesis-report` | 生成不渲染原始不可信摘录的确定性观点报告 | 写本次运行目录 |

查看目录并验证配方：

```bash
python -m quantagent_platform catalog
python -m quantagent_platform validate-recipe recipes/historical_data_health.json --source sqlite
```

对现有审计数据库运行体检：

```bash
python -m quantagent_platform run recipes/historical_data_health.json \
  --source sqlite \
  --input 10_DailyNotes/signal_audit.sqlite3 \
  --output-dir artifacts/runs
```

把入口替换成 JSON 时只改参数，后续校验和报告步骤不变：

```bash
python -m quantagent_platform run recipes/historical_data_health.json \
  --source json \
  --input tests/fixtures/sample_signals.json \
  --output-dir artifacts/runs
```

每次运行生成独立 `run_id` 目录，保存原始标准包、步骤插件版本、契约、SHA-256、时间、状态和 Markdown 报告。默认离线；读取路径限制在输入文件所在目录，也可以用 `--allow-read-root` 显式缩小或扩展允许范围。

## 受控 Agent 入口

P1/P2 的 Agent 入口只从 `agent_catalog/catalog.json` 读取精确版本和 SHA-256。AgentManifest/SkillManifest 使用严格安全 YAML 解析和 Draft 2020-12 Schema 校验；锚点、别名、显式标签、merge key、重复键、路径逃逸、内容哈希不符、未知能力以及非 `verified` 目录项都会失败关闭。

查看目录并做只读预检：

```bash
python -m quantagent_platform agent-catalog
python -m quantagent_platform validate-agent builtin.data-health-research-agent \
  --agent-version 1.0.0 \
  --source json
```

通过 Agent 运行同一历史数据体检配方：

```bash
python -m quantagent_platform run-agent builtin.data-health-research-agent \
  --agent-version 1.0.0 \
  --source json \
  --input tests/fixtures/sample_signals.json \
  --output-dir artifacts/agent-runs
```

运行记录中的 `invocation` 会保存目录、Agent、Skill、Recipe 的精确版本和哈希。当前只实现自动 `before_run` 校验和 `max_steps`；`max_tool_calls`、墙钟时间、费用、人工暂停/恢复、模型选择、Tool Broker、Typed Handoff 和 Agent 间调用目前只是清单边界或后续阶段，不能宣称已动态执行。

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

授权请求可读取 `GET /api/v1/runs/{run_id}` 和 `GET /api/v1/runs/{run_id}/report`。刷新或重复 GET 不会修改运行目录、创建新任务或调用模型；报告响应会重新校验运行状态、最终数据包与 Markdown 文件哈希。详细契约和错误语义见 `docs/QUANTAGENT_READ_API.md`。

需要验证第一条写路径时，可改用 `serve-research` 显式登记本机 thesis 样本，并通过有幂等键的 `POST /api/v1/runs` 运行固定的离线研究 Agent。它不接受浏览器提供的路径或任意能力，也不是长任务队列或多用户 API；启动、契约和限制见 `docs/QUANTAGENT_SUBMISSION_API.md`。

同一 `serve-research` 服务还提供 `POST /api/v2/runs`、版本化状态查询和协作取消。它使用单进程有界工作线程，重启后不会自动重跑未完成任务；细节和限制见 `docs/QUANTAGENT_TASK_LIFECYCLE_API.md`。

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

现有 `agent_engine.py --mode daily` 仍是生产入口；它与插件报告共用同一提示词和渲染函数。本仓库仅用模拟传输验证 DeepSeek 适配器，未把真实外部调用标记为已验证。

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

首个回测引擎选择 [`bt`](https://github.com/pmorissette/bt)，固定版本 1.2.3。它使用 MIT 许可证、支持 Python 3.12，且直接面向组合权重和再平衡，适合当前因子研究阶段。选择记录及未选引擎的许可证和运行代价见 `docs/BACKTEST_ENGINE_DECISION.md`。

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

## 本地运行

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
| `RSS_FEEDS` | 内置多个来源 | 自定义来源，格式为 `source::url|source::url` |
| `QUANTAGENT_VERSION` | 未设置 | 可选的代码版本标识，用于审计记录 |

## 验证

在项目根目录执行：

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

`requirements-test.txt` 复用已锁定的平台运行依赖，并补充 API 测试客户端，供 Schema、清单、P2 研究夹具、P3a 只读 API 和完整离线回归使用。

现有测试覆盖：

- 试运行不写业务文件、不推送、不连接审计数据库。
- 同日重复执行的跳过条件，以及强制重跑行为。
- 模型响应异常、非法摘要和新闻重试隔离。
- 日报、推送、记忆与审计之间的执行顺序。
- SQLite 结构、校验、事务回滚及同日有效记录切换。
- 数据包哈希与时区约束、精选插件目录和配方兼容预检。
- SQLite/JSON 数据入口替换、原生包及运行血缘保存、体检报告生成。
- 日报上下文校验、离线分析重放、模型替换权限闸门和生产兼容报告。
- Qlib 子进程协议、显式权限、路径限制、超时/错误隔离，以及可选真实 StaticDataLoader 集成。
- `bt` 子进程协议、时区时间、至少一根 bar 的执行延迟、成本参数、等权基线和可选真实引擎集成。
- P2 研究请求、证据包和观点状态 Schema，Point-in-Time/哈希/标的校验，正反证据、失效条件、幂等修订、角色最小权限和不可信文本隔离。
- P3a 结果摘要 Schema、Bearer 认证、单用户访问边界、路径约束、报告/数据包篡改拒绝、ETag，以及重复 GET 不写文件、不创建运行。
- 路径越界、权限不足、未知插件及错误数据库的失败关闭。

2026-09-22 在基线提交 `12407081cb882ae526180145237f32093f83dffc`、Windows、CPython 3.12.8 和 UTF-8 模式下复跑：共运行 81 个测试，其中 79 个通过、0 个失败、2 个真实依赖测试因未配置隔离解释器而跳过。P0 规范变更后共运行 86 个测试，其中 84 个通过、0 个失败、2 个跳过；P1 Agent 入口为 96 个测试，其中 94 个通过；P2 观点跟踪为 106 个测试，其中 104 个通过；P3a 只读结果 API 为 113 个测试，其中 111 个通过、0 个失败、2 个跳过。分阶段完整结果见 `docs/COMPATIBILITY_TEST_MATRIX.md`。GitHub Actions 同时在 Windows 与 Linux 上运行完整离线测试。相关测试使用固定样本和模拟的网络与模型依赖；Qlib 与 `bt` 的真实集成测试只在显式提供各自隔离解释器时运行。测试结果说明所覆盖的程序行为通过检查，不代表任意外部项目、数据源或组合已经联调成功，也不代表研究状态、模型判断或观点建议具有经验证的真实性与收益表现。完整 P0 环境、跳过项和夹具哈希见 `docs/P0_BASELINE_REPORT.md`。Windows 传统 GBK 控制台无法编码现有日志中的 emoji，运行测试时应启用 UTF-8，例如 PowerShell 使用 `$env:PYTHONUTF8='1'`。

## 当前边界

- 新闻清洗和去重主要依赖规则、标识及文本指纹，尚未实现语义去重。
- 日报质量依赖数据完整性和模型输出；模型给出的置信度尚未进行历史校准。
- 已支持显式历史价格文件的离线结果回填；自动取价、交易日口径和完整收益评估仍属于后续工作。
- 已支持 `bt` 固定样本组合回测，但尚未验证真实行情的复权、交易日、可成交性、容量、冲击、部分成交或订单生命周期。
- AgentManifest、SkillManifest 加载器以及数据体检和观点跟踪两个精选 Agent 入口已实现；二者是隔离的固定组合，不构成 Agent 间协作。P3a 只提供单用户只读运行摘要和报告读取，不提供 OpenStock 页面、任务提交/取消或多用户授权。模型驱动选路、动态工具/费用/墙钟限制、人工暂停恢复、Tool Broker 和 Typed Handoff 尚未实现。
- 第三方行情和新闻源可能出现访问限制、数据缺失或接口变化。
- 数据库设计文档含后续规划，功能是否完成以当前源码和测试为准。

## 项目分工

这是由 Chen 发起并维护的个人项目。本人负责需求梳理、基础流程规划、运行结果核对与关键操作风险检查；AI 编程工具辅助生成基础框架、实现部分代码和提供排错建议。项目同时用于学习数据处理、异常隔离、状态存储和测试验证。

## 许可证

采用 [MIT 许可证](LICENSE)。第三方数据来源、依赖库及外部服务各自的使用条款仍然适用。
