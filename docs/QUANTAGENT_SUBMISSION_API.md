# QuantAgent 受控提交 API v1（P3c 首步）

此入口是**显式启用的本机、单用户、离线 thesis 样本提交**，不是任意研究任务网关。原有 `serve-results` 仍然只读。只有 `serve-research` 会增加 `POST /api/v1/runs`；其余 GET 读取和报告完整性校验沿用 P3a。

本页描述保留的同步 v1 入口。`serve-research` 后续增加的异步状态与协作取消入口使用独立的 `/api/v2/runs` 路径；见 [`QUANTAGENT_TASK_LIFECYCLE_API.md`](QUANTAGENT_TASK_LIFECYCLE_API.md)。两版幂等键分属不同命名空间，不能把同一个逻辑请求同时提交到两版。

## 启动与输入登记

先创建运行目录，选择一份满足 `quantagent.thesis_review_fixture.v1` 的本地 JSON 夹具，并由服务操作者登记它。客户端只能引用登记名，不能传路径或插件/Agent 选择。

```powershell
New-Item -ItemType Directory -Force artifacts/thesis-runs | Out-Null
$env:QUANTAGENT_API_BEARER_TOKEN = 'replace-with-at-least-32-random-characters'
python -m quantagent_platform serve-research `
  --run-root artifacts/thesis-runs `
  --subject local-owner `
  --host 127.0.0.1 `
  --fixture thesis=tests/fixtures/sample_thesis_review.json
```

启动时验证夹具契约并固定其原始字节 SHA-256；提交时再次检查。夹具必须在运行根目录外，且不能是符号链接。修改夹具后需重启服务并更新请求中的哈希。服务只能监听字面量回环 IP；没有公网或多用户部署模式。

## 提交契约

请求必须带 Bearer token、`Content-Type: application/json` 和每个逻辑提交稳定不变的 `Idempotency-Key`（16–128 个安全字符）。JSON 上限 4096 字节，拒绝重复键、额外字段、NaN 和无效编码。请求正文符合 [`quantagent.submit_run.v1`](../schemas/quantagent.submit_run.v1.schema.json)：

```json
{
  "contract_type": "quantagent.submit_run.v1",
  "fixture_id": "thesis",
  "fixture_sha256": "<registered-fixture-raw-byte-sha256>",
  "request_id": "request.btc.thesis.20260922"
}
```

`request_id` 必须与已登记夹具中的 `research_request.request_id` 一致。服务还校验该夹具的内部引用哈希、三步预算、零模型成本和固定 Agent/Skill/Recipe 身份。实际执行只允许 `builtin.research-agent@1.0.0`、适配的 thesis-tracker Skill、`thesis-tracker@1.0.0` 配方、确定性 JSON 来源插件，以及离线文件读写权限。它不能调用模型、网络或交易能力。

新提交在服务端完成后返回 `201` 和脱敏的运行摘要，`Location` 指向 `GET /api/v1/runs/{run_id}`；相同幂等键及完全相同的正文返回已有运行摘要（`200`），不会重复执行。相同键配不同正文返回 `409 idempotency_conflict`。本端点的成功及受控错误响应使用 `Cache-Control: no-store`，受控错误不返回 token、路径或原始证据。`run_id` 仍不是访问凭证。

## 当前边界

- 执行被移到服务端工作线程，但 HTTP 提交会等待这次**确定性离线**运行完成；没有持久队列、取消、重启后恢复或强制终止超时任务。客户端超时可用同一幂等键重试，不能换键盲目再提交。若进程在登记运行状态前中断，同键会保守返回 `409 submission_pending`，需要人工检查，不会自动重跑。
- 夹具由本机操作者预先登记并保持不变；提交前校验哈希，但本地能改写文件的攻击者不在该边界内。未来通用提交应将不可变输入副本、来源和授权主体绑定到持久任务队列。
- 这是 P3c 的第一条可验证写路径，不代表 P3 的任务取消、长任务预算强制执行、OpenStock“运行研究”按钮、多用户授权、生产部署或真实外部数据已完成。
