# 现有 Monitor / Daily 引擎

## 职责与边界

本目录登记旧引擎兼容入口，运行源码仍在仓库根。Monitor/Daily 的执行顺序已移入工作流；入口通过显式回调提供原网络、模型和文件能力，审计实现由启动工厂组装。

## 文件导航

[agent_engine.py](../../../agent_engine.py)是兼容入口；[使用说明](../../USAGE.md#本地运行)集中维护安装、环境变量与运行命令。

[legacy_workflows.py](../../../quantagent_platform/legacy_workflows.py)保存两个流程；[legacy_ports.py](../../../quantagent_platform/legacy_ports.py)定义公开回调及审计绑定；[legacy_bootstrap.py](../../../quantagent_platform/legacy_bootstrap.py)惰性提供原审计类与质检函数。

基础异常归包外[signal_audit_contracts.py](../../../signal_audit_contracts.py)，单独导入存储不触发插件初始化。

## 对外接口

`python agent_engine.py --mode monitor`持续采集，`--mode daily`生成日报；`--mode weekly`仅提示未实现。外部服务失败、幂等和写入行为须保留原语义。

`QuantAgent()`及原方法签名保留；两个流程在调用时捕获配置和回调，不承诺运行中的配置热切换。原 `SignalAuditStore`、质检函数和审计错误别名保留；未绑定或无效审计工厂显式失败，不静默回退。原 `source_sha256`仍读取根入口源码。

## 依赖规则

入口只向新工作流和 ports 引用，不直接引用日报业务或具体审计适配器；工作流不访问入口私有变量或直接文件 IO。启动组装的具体审计依赖已登记；普通函数内导入仍纳入源码检查。规则和当前状态见[架构规范](../../ARCHITECTURE.md)。

## 数据与权限

读取新闻、行情和配置，正式运行写日报、状态及审计，可选消息推送。`DRY_RUN=true`阻止业务写入和推送，仍可能调用网络及模型；私人资料和权限边界遵守架构规范。

## 测试与验收

原离线测试及范围见[测试导航](../../../tests/README.md)；真实模型、行情、消息和部署需另行验收。

本批命令、实际结果及未测范围见 [D006](../../features/d006-legacy-workflows.md)。

## 已知限制

采集与日报分开启动，完整周报及学习业务未实现。旧入口的网络、模型和文件实现保留，未整体迁移为独立适配器目录；离线替身通过不能代替外部服务验收。
