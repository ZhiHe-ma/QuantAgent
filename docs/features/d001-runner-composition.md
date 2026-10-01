# D001：运行器与默认插件组装分离

```json
{
  "branch": "refactor/d001-runner-composition",
  "base_commit": "76382aa8062c03141c29ad51e1562ff6b3124708",
  "tested_commit": "7d7a840dcda0635f0512a21a1a1bab5c70f4e74b",
  "components": ["runner", "default-composition", "compatibility-exports", "architecture", "acceptance-tests"],
  "readme_unchanged": {}
}
```

## 目标与非目标

执行 [整改清单](../architecture/remediation.md) 的 D001：运行器只执行已注入的插件，具体默认插件由独立组装器创建。保留 Python 默认调用、CLI、HTTP、配方、权限预检与审计行为。本批不实现学习、训练、交易或 D002–D006 的业务整改。

## 涉及模块

runner 增加默认注册表工厂的公开注入接口；bootstrap 负责具体插件与目录校验；原包入口初始化兼容默认工厂。architecture 登记新组装能力、缩减实际消除的引用边；acceptance-tests 验证兼容及边界。

## 接口或数据变化

`RecipeRunner(registry)` 继续使用调用者的注册表。`RecipeRunner()`、`AgentRuntime()`、原 `default_registry()` 及包根 Python 导出保持可用；每次取得独立默认注册表。不改配方、插件、Packet、CLI/HTTP 格式、存储或权限。

包根保留为兼容启动门面，只在初始化时调用组装器，不增加业务类型统一导出。门面可依赖已精确登记的 bootstrap；其他层的方向及禁止从业务引用包根的规则不变。核对原登记表的所有允许关系，确保这项启动规则不会把原存量违规转为合法引用。

## 新增依赖

新增 `quantagent_platform.bootstrap` 能力及包入口到它的启动引用；运行器不引用它。没有新增第三方库、动态加载、延迟导入或存量豁免。

## 测试证据

实施环境：2026-10-02，Windows 11 10.0.22631、仓库外 Python 3.12.8，原 `.venv/Lib/site-packages`，Import Linter 2.8、grimp 3.13；UTF-8 输出。基线为首个 JSON 的提交。

完整离线测试针对实现提交 `7d7a840dcda0635f0512a21a1a1bab5c70f4e74b` 的代码内容；后续验收记录提交只补充文档。

基线 `python -m unittest discover -s tests -v`：283 项，0 失败，原 6 项跳过，57.791 秒。

- 新增反例实际先失败：独立组装器缺失、运行器越界引用、假值显式注册表被丢弃及启动注入规则不支持；拆分后通过。
- `python -m unittest discover -s tests -v`：295 项，0 失败，原 6 项跳过，62.457 秒；新增 8 项兼容测试、4 项门禁测试。
- `python -m tools.architecture --base-ref 76382aa8062c03141c29ad51e1562ff6b3124708 --branch refactor/d001-runner-composition --report artifacts/architecture/d001-runner-composition/gate.json`：PARTIAL_COMPLIANCE，43 个模块、27 条原存量，Import Linter 退出 0，无新增违规。
- 同一扫描器复核：42 → 27 条、2 → 1 组循环。移除 D001 的 12 条及随循环解除的 D002 的 3 条；没有转移豁免，D002 混合职责仍未整改。
- 复核原登记表的 1764 对允许关系不变；61 个既有代码/配置资产哈希不变。默认组装函数体与原实现一致，运行器除构造器外的 5 个方法 AST 一致；29 项目录、12 个包根导出及版本保持。假值注册表现在按显式注入处理。

原始 RED、完整离线日志、静态图与哈希证据保留在忽略的 `artifacts/architecture/d001-runner-composition/`。未运行：Linux/CI、真实 bt/Qlib、私有 P4 输入、真实模型/行情/消息、部署及生产验收；另 3 项 Windows 符号链接用例因原权限条件跳过。固定 CLI/HTTP、预检、审计和配方的兼容由既有离线测试覆盖。

### Task 1: 分离组装与执行并验证兼容

1. 保存基线静态图、默认目录、公开导出与配方/契约哈希；编写反例并实际观察失败。
2. 将原默认目录校验和插件构造移入 bootstrap；运行器提供工厂注入，包入口配置兼容默认值。
3. 精确登记 bootstrap；允许启动门面调用登记组装器，同时验证业务反向引用、循环和私有引用仍失败。
4. 运行新增测试及完整离线测试；逐条移除实际已消除的基线引用，不转移或扩大豁免。
5. 更新相关 README、整改状态及本节验收证据，运行架构门禁并提交本地变更。

Expected: 无新增架构违规；原 Python 默认调用、CLI 目录、HTTP 离线测试、配方哈希、预检及审计兼容。Import Linter 退出 0，基线只能缩减。

Review focus: 包初始化顺序、默认工厂与显式注册表的隔离、原导出/目录/配方兼容、启动规则是否隐藏债务、学习与数据归属边界。

## 回滚方式

回退本批提交即可恢复原运行器、规范与基线；未改变数据格式或已有运行目录。工作区原有项目方案删除不属于本批，不纳入提交。

## 遗留问题

D002–D006 继续按整改清单分批执行；清零前仍标记部分符合。学习流程只形成候选经验，验证并取得既定确认后由数据所属模块更新；原决定及理由保留，更正追加记录。不得把离线验证推广为真实模型、数据库、Linux/CI 或生产验收。
