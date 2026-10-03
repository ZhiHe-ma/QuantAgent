# QuantAgent

[English](README.md) | 简体中文

把新闻和证据整理成可回看的研究报告，投资决定由用户掌握。

## 当前能力

| 能力 | 使用范围 |
| --- | --- |
| 新闻采集与日报 | Monitor 收集新闻，Daily 结合行情和历史摘要生成日报；需要外部服务配置 |
| 离线观点跟踪 | 使用结构化输入，整理支持、反对证据和失效条件 |
| 历史核对 | 数据体检、包重放、显式历史价格的结果回填 |
| SEC 研究与复核 | MARA / Riot 限定样本、固定单跳复核；验证范围见验收记录 |
| Qlib / bt | 实验性固定样本研究与回测，按需使用隔离环境 |

这是需要自行安装的研究工具。多用户页面、持有档案和持续学习仍是开发方向；各工作树分别验收，不能当作一个已发布版本。

## 开始使用

需要 Python 3.12 或更新版本。先按[使用说明](docs/USAGE.md#本地运行)准备虚拟环境；在仓库根目录运行：

```bash
python -m pip install -r requirements.txt
python -m quantagent_platform run-agent builtin.research-agent --agent-version 1.0.0 --source thesis-json --input tests/fixtures/sample_thesis_review.json --title "QuantAgent 离线观点报告" --output-dir artifacts/first-report
```

这份合成报告不调用模型、不使用真实行情。打开 `artifacts/first-report/<运行目录>/thesis_review_report.md` 查看结果。安装依赖仍需网络。

真实新闻流程的配置、命令和可选参数统一放在[使用说明](docs/USAGE.md)。Monitor 与 Daily 分别启动；`DRY_RUN=true` 仍可能联网、调用模型并产生费用。

## 阅读入口

| 要了解什么 | 文档 |
| --- | --- |
| 怎么运行 | [使用说明](docs/USAGE.md) |
| 功能入口与接口 | [平台导航](quantagent_platform/README.md) |
| 开发边界与数据归属 | [架构规范](docs/ARCHITECTURE.md) |
| 文件分类与文档维护 | [开发与测试](docs/DEVELOPMENT_TESTING.md) |
| 怎么验证 | [测试导航](tests/README.md)、[兼容性矩阵](docs/COMPATIBILITY_TEST_MATRIX.md) |
| 历次改动 | [功能分支说明](docs/features/README.md) |

报告供研究核对，不承诺收益。真实源、部署和恢复需分别验收；密钥、数据库及私人记录留在本地。项目不连接券商下单，不自动修改用户规则。

## 项目与许可

Chen 发起并维护项目，负责需求、流程和结果核对；AI 编程工具辅助实现与排错。采用 [MIT 许可证](LICENSE)，第三方数据和服务遵守各自条款。
