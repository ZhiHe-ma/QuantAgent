# D003：API 路由组装与共享边界

```json
{
  "branch": "refactor/d003-api-composition",
  "base_commit": "f02a0e2bdf6dacf1b60222386e2b2b5c80e22d5b",
  "components": ["http-api", "api-contracts", "api-factory-port", "api-composition", "compatibility-exports", "architecture", "acceptance-tests"],
  "readme_unchanged": {
    "architecture": "仅登记新增契约、工厂接口与组装入口，缩减实际消除的循环边；检查器、依赖规则和 CI 命令不变。"
  }
}
```

## 目标与非目标

执行[整改清单](../architecture/remediation.md)的 D003：移除五条 API 循环边，由启动组装器安装结果、提交和任务路由。共享类型归纯契约，文件读取与样本准入归所属 API 主机的公开接口；不迁移整个 HTTP 主机，不修改 D004–D006、学习或交易。

## 涉及模块

`result_api`、`submission_api`、`task_lifecycle_api` 仅安装各自路由；`api_bootstrap` 组装应用，包入口只注入默认工厂。`api_contracts` 保存共享模型、错误、配置与样本引用；`api_storage` 保存原结果存储及有界读取；`api_requests` 保存原样本登记和有界请求解析。后两者仍属于既有 http-api 能力，不改变原模块归属、层级或数据所属方。

## 接口或数据变化

原 `result_api.create_app(config, submission=None)`、`ApiConfig`、`ResultStore`、请求/响应/错误导入以及 `submission_api.SubmissionConfig` 等所属模块入口继续兼容。引入公开路由安装、存储读取和请求准入接口；旧路径保留别名。默认启动不加载可选 FastAPI/Pydantic/uvicorn 依赖，也不创建应用、工作线程或运行目录；只有请求创建应用时组装。

## 新增依赖

新增上述契约、工厂接口、组装、存储和请求文件；精确登记新能力及指向它们的依赖。Pydantic 作为既有 HTTP 模型的纯依赖登记到新契约，不新增第三方包。不修改门禁规则、扩大旧能力间允许关系或增加豁免。

## 测试证据

环境：2026-10-02，Windows 11、仓库外 Python 3.12.8、原 `.venv/Lib/site-packages`。基线完整离线命令 `python -m unittest discover -s tests -v`：305 项，0 失败，原 6 项跳过，65.894 秒。源码目标为首个 JSON 的提交；原日志、静态图和兼容核对保留在忽略的 `artifacts/architecture/d003-api-composition/`。

命令从仓库根运行，设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`PYTHONPATH=<本仓库>/.venv/Lib/site-packages`；实际解释器为 `C:\Users\yj\AppData\Local\Programs\Python\Python312\python.exe`，门禁使用 `D:\Git\cmd` 加入 PATH。HTTP 捕获及复核使用原 FastAPI 0.141.1、Pydantic 2.13.5、httpx2 2.13.0；Import Linter 2.8 / grimp 3.13，未新增安装。

| 验证 | 命令与实际结果 |
| --- | --- |
| RED → GREEN | `python -m unittest tests.architecture.test_api_boundaries tests.contract.test_api_contracts tests.integration.test_api_composition -v`：改动前 3 个断言失败、5 个缺失接口错误、2 个原行为通过；实现后 10/10 通过，1.753 秒 |
| 完整离线 | `python -m unittest discover -s tests -v`：315 项、0 失败、原 6 项跳过，130.678 秒 |
| 兼容核对 | `python artifacts/architecture/d003-api-composition/verify_compatibility.py`：75 个原资产哈希、70 项源码 AST、2,116 个原能力允许关系、12 项包根公开导出和 29 个默认插件保持；读取/提交应用的原 HTTP schema、错误与响应完全匹配 |
| 静态结果 | 52 个源码模块，D003 五条循环边全部消除，剩余 10 条，无循环、新豁免或原能力间依赖放宽 |
| 架构与文档门禁 | `python -m tools.architecture --base-ref f02a0e2bdf6dacf1b60222386e2b2b5c80e22d5b --branch refactor/d003-api-composition --report artifacts/architecture/d003-api-composition/gate.json`：通过，`PARTIAL_COMPLIANCE`，Import Linter 返回 0 |

原 HTTP 样本在实现前捕获，SHA-256 为 `99868153665fdcfd6658bebac09b2a41529bee5e975240e11b951c36a04af0b0`，验收未覆盖该预期。实际测试提交和独立审查结果在完成本地提交后补录。

### Task 1: 分离路由组装与共享 API 接口

1. 复核基线、保留原用户删除；捕获原 HTTP 路由、模型 schema、错误、公开导出、固定目录/配方/样本哈希及源码边界。
2. 新增循环、端点相互导入、私有读取、工厂注入及启动依赖反例，观察预期失败。
3. 提取共享纯模型/错误和 API 主机存储、请求准入；保留原安全检查、类型身份及旧入口，编排改用公开接口。
4. 三个 API 各自安装路由；启动组装器绑定原认证、错误处理与生命周期，兼容 create_app 通过抽象工厂委托。
5. 登记新增能力、接口和文件；不放宽规则或新增豁免，精确移除实际消除的五条循环边。
6. 回归 Python 导出、CLI、HTTP 路径/响应/鉴权/缓存、请求上限、幂等、取消、失败与重启语义；运行完整离线测试和门禁，更新当前 README 与实际验收版本。
7. 本地提交，执行一次独立只读审查，归档本批记录，保留工作树。

Expected: 五条 D003 循环边清零且无新增违规；整体剩余十条仍部分符合；原 HTTP 契约与固定配置兼容，可选 HTTP 依赖不影响核心导入，测试与 Import Linter 通过。

Review focus: 兼容 create_app 的默认注入和可选依赖；认证/错误处理/健康信息/缓存头与路由顺序；样本路径及哈希、请求流上限、幂等与竞态；取消、关闭与重启中断行为；公开存储方法沿用授权校验，不直接暴露原始状态给 HTTP 调用者；新契约无 IO/工作流导入，不通过规则或登记改层级掩盖循环。

## 回滚方式

回退本批提交恢复原组装、引用和精确基线；不迁移或改写现有 run.json/task.json、研究或审计数据。原用户项目方案删除不纳入提交。

## 遗留问题

Linux/CI、真实外部服务、私有 P4、真实 bt/Qlib、权限受限的 Windows 链接场景、部署和生产未运行；六项原跳过保持独立记录。D004–D006 与 D002 的非阻塞类型改进留待对应批次；本地通过不能证明多进程队列、跨账户隔离或未来学习业务。
