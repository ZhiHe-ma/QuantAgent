# 能力登记与存量整改

## 职责与边界

登记代码归属与精确存量豁免，业务接口由所属模块说明。

## 文件导航

[components.json](components.json)登记能力；[legacy-baseline.json](legacy-baseline.json)保留存量；[remediation.md](remediation.md)安排整改。

## 对外接口

components version=1：能力包含 id、kind、modules、public_modules、allows、external_dependencies、readme、data_owner、assets。目录资产以 `/` 结尾，directory_roots 发现需要独立登记及 README 的子目录。基线包含起点提交、规则、引用边/成员、理由和整改任务。

## 依赖规则

规则及豁免收缩要求见[架构规范](../ARCHITECTURE.md)；modules、依赖与豁免禁止通配。

## 数据与权限

登记不会授予运行权限。每项 data_owner 必须符合架构规范，私人资料不放入登记文件。

## 测试与验收

按[工具说明](../../tools/architecture/README.md)运行检查，在对应分支说明记录证据。

## 已知限制

当前部分符合，存量以基线为准；静态登记不能证明运行时隔离或业务正确。
