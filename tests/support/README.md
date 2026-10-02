# 共享测试支持

## 职责与边界

集中路径定位、SEC 合成输入构造器和可执行替身。供自动测试复用，不包含 TestCase，不调用真实 SEC、模型或账户服务，不被产品代码导入。

## 文件导航

[paths.py](paths.py) 定位仓库；[sec_samples.py](sec_samples.py) 保存原 SEC 测试构造器；[fakes](fakes/README.md) 保存 bt/Qlib 的离线 worker。静态 JSON/CSV/TXT 仍在 fixtures，测试入口见 [测试导航](../README.md)。

[p5_samples.py](p5_samples.py) 构造临时合成 P4 与批准登记，固定 SEC 检索时间及研究时钟，供 P5 兼容测试复用。

## 对外接口

`repository_root(start: Path) -> Path` 从指定文件所在目录向上查找最近同时含 agent_engine.py 文件及 quantagent_platform、recipes、tests 目录的根，找不到抛 FileNotFoundError；`ROOT` 是本文件定位的仓库根，与 cwd 无关。

平铺用例作为包运行时从 tests.support.paths 导入，直接运行文件时从同一个 support/paths.py 导入，以保留原单文件入口的启动顺序；两种方式使用相同标记定位规则，不恢复固定父目录深度。

分类目录的直接脚本入口先按当前文件祖先找到本仓库 tests/support，再导入共享 ROOT 校验完整仓库标记；包发现时不执行这段引导，资源与配方仍由共享路径定位。

SEC 提供 `ISSUERS`、`make_payloads()`、`make_responses(payloads=None, *, retrieved_at=None)`，保留合成数据、JSON 序列化、哈希和默认 UTC 时间减一分钟的原语义。fakes 在显式测试子进程中读取协议输入并写测试输出。

`build_approved_source(root)` 返回批准登记路径与 P4 运行根；在测试临时目录执行原离线配方、写入合成文件，SEC 获取由固定响应替身提供。固定研究时钟只在构造期间生效；不导入用例、不联网、不改写产品时间规则。

## 依赖规则

路径只依赖标准库；SEC 支持使用既有 SEC_URLS/SecResponse 公共类型。支持模块不导入测试用例，不成为产品内部共享库。测试与生产依赖的登记范围不同，生产规则仍见 [架构规范](../../docs/ARCHITECTURE.md)。

## 数据与权限

只生成原有虚构发行人数据，保留测试临时目录、允许根和子进程权限。没有私人账号资料或真实外部服务凭据；fake worker 不扩张产品权限。

## 测试与验收

运行 `python -m unittest discover -s tests -p test_support_paths.py -v` 验证嵌套路径、缺失根标记、cwd 变化及从其他 cwd 启动六个平铺和六个已分类测试脚本的 --help 入口。入口用例不执行业务测试，只检查启动方式。bt/Qlib 原测试验证离线协议、拒绝越权、超时和失败行为；真实后端按原环境条件跳过。实际全套数量及用例映射见 [分支说明](../../docs/features/file-classification.md)。

## 已知限制

路径依赖约定的四个仓库标记；非本项目目录会失败。SEC 默认时间仍随运行时变化，需固定时传 retrieved_at。当前只整理首批支持，其他平铺测试后续随能力整改。
