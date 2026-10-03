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

R001 新增所属恢复接口：capture_daily_inputs 严格读取 Memory／文件前像并确认审计提供方支持恢复；prepare_recovery_audit 在交付前校验；project_daily_report／project_daily_memory 在短投影锁内校对目标与前像，用相同 UTF-8 字节原子替换。内容冲突需人工检查，较新 Memory 返回 superseded。send_wecom_result 区分 confirmed／failed／unknown／not_configured，原 push_to_wecom 继续返回 bool；daily_ports 对旧回调 False 保守标记 unknown。commit_frozen_audit 交给已注入审计实例，入口不访问其内部数据库。Daily／Monitor 均已接入。

正式 Daily 已接入恢复：先校验研究与胶囊并冻结快照，再交付报告、消息、Memory、审计。同日未完成复用原编号／研究，FORCE 不能绕过；已有完整历史继续跳过，半成品需人工处理。recover status／confirm／abandon 不构造研究引擎；retry 通过完整所属 ports 恢复指定任务。

Monitor 已接入 durable 观察、推理决议及逐项投影确认；原评级、数量、指纹和重试预算保持。capture_monitor_state 严格核对旧 JSON；project_news_record 经短投影锁和唯一临时文件原子替换。旧已达到预算的隔离记录不再请求模型，源新闻仍存在时只补去重。

## 已知限制

采集与日报分开启动，完整周报及学习业务未实现。旧入口的网络、模型和文件实现保留，未整体迁移为独立适配器目录；离线替身通过不能代替外部服务验收。
