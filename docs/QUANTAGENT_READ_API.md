# QuantAgent Read API v1

P3a 提供一个本地、单用户、只读的 HTTP 边界，让后续 Web 页面先展示 QuantAgent 已经完成的运行和 Markdown 报告。它不提交、取消或重跑任务，不接入 OpenStock，也不改变 `RecipeRunner` 的执行授权。

## 启动

服务要求一个已存在且不是符号链接或 Windows junction 的运行根目录，以及至少 32 个字符的 Bearer token。token 只从指定环境变量读取：

```powershell
$env:QUANTAGENT_API_BEARER_TOKEN = 'replace-with-at-least-32-random-characters'
python -m quantagent_platform serve-results `
  --run-root artifacts/thesis-runs `
  --subject local-owner `
  --host 127.0.0.1 `
  --port 8765
```

默认只允许 loopback。`--allow-non-loopback` 只是防止误监听的显式开关，不会自动提供 TLS、反向代理、速率限制或生产级身份系统；跨主机部署前必须另行设计并验证这些边界。

## 端点

| 方法与路径 | 认证 | 响应 |
| --- | --- | --- |
| `GET /healthz` | 无 | 非敏感健康状态，不返回目录、token 或运行详情 |
| `GET /api/v1/runs/{run_id}` | Bearer | 符合 `quantagent.read_api.run_summary.v1` 的脱敏运行摘要 |
| `GET /api/v1/runs/{run_id}/report` | Bearer | 完整性验证后的 UTF-8 Markdown；支持精确 ETag 与 `If-None-Match` |

摘要只暴露运行状态、时间、是否离线、精确 Agent/Skill/Recipe 引用、步骤插件/契约/哈希、最终契约/哈希、失败类型和报告链接。它不会返回允许根目录、输入路径、数据包路径、原始证据、错误消息或密钥。

示例：

```powershell
$headers = @{ Authorization = "Bearer $env:QUANTAGENT_API_BEARER_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8765/api/v1/runs/<run-id> -Headers $headers
Invoke-WebRequest http://127.0.0.1:8765/api/v1/runs/<run-id>/report -Headers $headers
```

`run_id` 只定位资源，不承担认证。重复请求和浏览器刷新不会创建运行、写文件、调用模型或增加研究版本。

## 访问与完整性规则

- P3a 的 subject 由服务配置固定，所有有效 token 请求都映射到该 subject；这只是单用户部署边界，不是多租户身份系统。
- 运行 ID 必须匹配受限字符集，且只能解析为配置根目录的直接子目录；运行目录、状态文件、数据包和报告符号链接都会被拒绝。状态中保存的绝对目录不受信任，服务只取安全文件名并重新锚定到当前运行目录，不能借存储路径跨运行读取。
- JSON 使用 UTF-8、大小上限、重复键拒绝和 NaN/Infinity 拒绝；对外错误不会包含本地路径或原始内容。
- 报告只对 `completed` 且最终契约为 `quantagent.report.v1` 的运行开放；服务重新校验最终步骤状态、包契约、包内容哈希、报告格式和文件 SHA-256。
- 响应使用 `Cache-Control: private, no-store`；Markdown 还使用 `X-Content-Type-Options: nosniff` 和固定下载文件名。
- 当前哈希检查可以发现状态、包或报告不一致，但本地运行目录仍属于受信任的存储边界；能同时重写内容和全部相关哈希的本机攻击者不在 P3a 的防护声明内。

## 错误语义

| 状态 | 错误码 | 含义 |
| --- | --- | --- |
| `401` | `authentication_required` | 缺少或使用错误的 Bearer token，并返回 `WWW-Authenticate: Bearer` |
| `403` | `access_denied` | 已认证主体不拥有当前运行集合 |
| `404` | `run_not_found` | 运行不存在，或运行 ID/目录边界不合法 |
| `409` | `result_unavailable` | 运行没有已完成的 Markdown 结果 |
| `409` | `artifact_integrity_error` | 运行状态、数据包或报告未通过完整性检查 |

## 当前不包含

- OpenStock 页面、CORS 策略或前端会话管理；
- 任务提交、取消、排队、刷新恢复或幂等写接口；
- 多用户、资源级 ACL、token 轮换、审计登录或外部身份提供方；
- TLS、反向代理、速率限制、操作系统级存储隔离；
- 对原始证据、任意附件或非 Markdown 最终产物的读取。

下一阶段应先用独立 Web 项目消费这两个只读端点并验证错误状态；只有读路径稳定后，才增加带请求契约、预算、权限和幂等键的任务提交接口。
