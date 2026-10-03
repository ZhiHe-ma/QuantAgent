# Monitor / Daily 引擎

## 职责与边界

仓库根引擎保持兼容入口，并拥有模型／网络／文件操作。Daily／Monitor 顺序由工作流编排，审计与恢复实现由启动工厂注入。正常公开结果保持，失败路径按 R001 继续原任务。

## 文件导航

[agent_engine.py](../../../agent_engine.py) 提供兼容入口和所属操作；[legacy_ports.py](../../../quantagent_platform/legacy_ports.py) 定义回调／工厂，[legacy_bootstrap.py](../../../quantagent_platform/legacy_bootstrap.py) 惰性组装。流程见 [平台导航](../../../quantagent_platform/README.md)，恢复核心见 [恢复目录](../../../quantagent_platform/recovery/README.md)，命令见 [使用说明](../../USAGE.md#本地恢复)。

## 对外接口

`QuantAgent()`、原 Python 方法和审计别名保留。CLI daily 生成／恢复日报，monitor 持续观察，weekly 提示尚未实现；recover 提供只读 status、明确 retry、两个消息 confirm 及带理由 abandon。状态／确认／终止不构造研究引擎。

`daily_ports()`／`monitor_ports()` 绑定当前回调；旧显式无 recovery 的 ports 保留原流程。Daily 先校验并冻结，再 report → message → Memory → audit；正常返回 report/capsule/audit，完成重跑精确 skipped，未完成附状态／编号／步骤。FORCE 不绕过未完成任务。

capture_daily_inputs／capture_monitor_state 严格核对状态；project_daily_report／project_daily_memory／project_news_record 经短锁、前像或原指纹对账和唯一临时文件原子替换。冲突需人工处理，较新 Memory 返回 superseded。send_wecom_result 区分四种消息结果，push_to_wecom 继续返回 bool；旧回调 False 映射 unknown。commit_frozen_audit 委托同一已注入审计实例，不访问内部数据库。

## 依赖规则

入口引用公开工作流、ports 与恢复契约，不导入具体存储；工作流不读入口私有变量或执行 IO。具体实现仅由指定启动组装注入；函数内导入照常检查，边界见 [架构规范](../../ARCHITECTURE.md)。

## 数据与权限

保存公共研究、文件投影、恢复及审计事实；正式运行可选消息推送。dry-run 阻止业务写入／消息／恢复事件，仍可能请求模型和网络。实例／账户和私人数据归属遵守共同规范。

## 测试与验收

离线测试见 [测试导航](../../../tests/README.md)。D006 的迁移证据见 [D006](../../features/d006-legacy-workflows.md)，当前恢复证据见 [R001](../../features/r001-recovery-resume.md)；真实模型、行情、消息、Linux、CI 与部署结果分别填写。

## 已知限制

单机同目录恢复；无完整快照的旧半成品不能补造研究。未知消息需人工确认，不承诺真人阅读或恰好一次发送。运行中配置热切换、跨主机恢复、学习和交易不在本批范围。
