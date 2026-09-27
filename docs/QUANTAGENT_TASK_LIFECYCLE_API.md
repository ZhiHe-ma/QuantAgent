# QuantAgent 本机任务生命周期 API v2（P3e 受控切片）

`serve-research` 在既有同步 `POST /api/v1/runs` 之外，新增异步任务入口。`serve-results` 仍然只读，不提供任何 v2 路由。v2 沿用 `quantagent.submit_run.v1` 请求正文、Bearer 认证、服务端预登记的 thesis 夹具，以及固定的离线 Agent/Skill/Recipe；客户端仍不能指定路径、插件、模型或权限。

## 端点与契约

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `POST` | `/api/v2/runs` | 携带 `Idempotency-Key` 提交；新任务返回 `202` 和 `Location`，同键同正文重试返回现有状态（`200`） |
| `GET` | `/api/v2/runs/{run_id}` | 读取 [`quantagent.run_status.v2`](../schemas/quantagent.run_status.v2.schema.json) 状态；不启动或重跑任务 |
| `POST` | `/api/v2/runs/{run_id}/cancel` | 排队任务立即记为取消（`200`）；运行中记录取消请求（`202`），在下一步骤开始前协作生效 |

以上端点都要求原有 Bearer token，并使用 `Cache-Control: private, no-store`。`run_id` 不是凭证。只有 `completed` 状态提供既有 v1 摘要和 Markdown 报告链接；`cancelled` 和 `failed` 只返回脱敏的失败类型，不返回路径、密钥或原始异常消息。v1 的摘要枚举没有被悄悄扩展；取消状态只由 v2 契约表达。

例如在已按 [`serve-research` 说明](QUANTAGENT_SUBMISSION_API.md)登记夹具后，向 `/api/v2/runs` 发送相同的 JSON 正文，增加稳定的 `Idempotency-Key`。随后按 `Location` 查询状态，必要时对同一 `run_id` 发起取消。请求体仍须包含登记名、登记时的原始字节 SHA-256、研究请求 ID 和 `quantagent.submit_run.v1` 契约类型。

## 状态语义

- `queued`：已持久登记，尚未执行。单进程只有一个工作线程，最多接收 8 个未处理任务；超限返回 `429 task_capacity_reached`，不创建新记录。
- `running`：工作线程已开始；`cancel_requested=true` 表示取消意图已记录，**不**表示插件已经停下。若最后一步已经结束，结果仍可能是 `completed`。
- `completed`：运行器成功完成，可通过返回的既有 v1 链接读取受认证和完整性检查的结果。
- `failed`：执行失败；只公开异常类型，原始信息保留在受信任的本地运行审计中。插件或回调单独抛出 `RunCancelled` 不会伪造取消状态。
- `cancelled`：排队时取消而未创建运行目录，或运行器在步骤边界确认取消；重复取消返回当前状态，不重跑。
- `interrupted`：持久记录属于已不再管理该任务的进程，或本进程工作线程异常退出；在登记夹具哈希仍匹配时，同键重试只返回该状态，不自动执行第二次。需要人工检查运行目录与审计。

登记记录保存在运行根目录内的 `.tasks-v2`；运行结果仍使用原有独立 `run_id` 目录。v2 的幂等键命名空间与 v1 分开，**不要把同一个逻辑请求同时提交到 v1 和 v2**。同一个 v2 键配不同正文返回 `409 idempotency_conflict`。已登记任务即使原夹具随后发生变化，同键重试仍只读已有状态；新键提交则必须重新通过原始字节哈希检查。

## 当前边界

这是单机、单进程、单用户、固定离线夹具的工作线程，不是生产级持久队列。服务关闭时会请求正在管理的任务协作停止，并停止接收新的队列工作；进程重启不自动恢复。多个服务实例不得共享同一个运行根目录；没有跨进程锁、强制杀停插件、墙钟预算强制执行、通用重试、外部数据源、多用户授权或交易权限。取消只在插件步骤之间生效，不能撤销已完成步骤的副作用。真实长任务、恢复和预算能力需要独立设计与验收。

OpenStock 写界面不属于本后端仓库。截至 2026-09-24，独立 OpenStock fork 的[受控任务页面 PR #2](https://github.com/ZhiHe-ma/OpenStock/pull/2) 已建立并通过其范围内 CI，仍为草稿；它只提交服务端固定离线样本，不构成整合或部署验收。
