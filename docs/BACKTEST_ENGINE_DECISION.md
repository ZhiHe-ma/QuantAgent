# Backtest Engine Decision v1

## 结论

首个受控回测卡带选择 `bt==1.2.3`。选择范围只覆盖研究阶段的组合权重、再平衡、比例交易成本和基线比较；不扩展到实盘执行。

## 选择理由

| 候选 | 当前边界 | 决策 |
| --- | --- | --- |
| `bt` | MIT；Python >=3.9；有 Python 3.12 Windows wheel；直接支持目标权重、再平衡、佣金和组合结果 | 首选，用独立 Python 子进程接入 |
| QuantConnect LEAN | Apache-2.0；事件驱动能力完整；本地 CLI 通常依赖 Docker，运行与数据约定明显更重 | 后续需要订单生命周期和更真实撮合时再评估 |
| NautilusTrader | LGPL-3.0；事件驱动、Rust 内核；当前 2.x 文档对应 release candidate，1.x/2.x API 有边界 | 等 2.x 稳定并明确实盘路线后再评估 |
| VectorBT | 当前许可证为 Apache-2.0 加 Commons Clause，并非无附加限制的 OSI 开源许可 | 不作为默认开源卡带 |
| Backtesting.py | AGPL-3.0 | MIT 主仓默认不接入；需要法律边界评估 |
| Backtrader / Freqtrade | GPL-3.0；前者维护和现代 Python 兼容声明较弱，后者更偏完整交易机器人 | 不作为首个 MIT 项目默认卡带 |

上游依据：

- `bt`：<https://github.com/pmorissette/bt>，<https://pypi.org/project/bt/1.2.3/>
- LEAN：<https://github.com/QuantConnect/Lean>，<https://github.com/QuantConnect/lean-cli>
- NautilusTrader：<https://github.com/nautechsystems/nautilus_trader>
- VectorBT：<https://github.com/polakowo/vectorbt/blob/master/LICENSE.md>
- Backtesting.py：<https://github.com/kernc/backtesting.py>
- Backtrader：<https://github.com/mementum/backtrader>
- Freqtrade：<https://github.com/freqtrade/freqtrade>

## 首版验收边界

- 输入必须明确时间戳时区、价格语义、标的、收盘价和信号。
- 信号至少延迟一根 bar，首版按下一可用 bar 的收盘价调整目标权重。
- 只做多；选择信号高于阈值的前 N 个标的并等权。
- 手续费和滑点作为成交金额的固定比例成本分别记录、合并执行。
- 必须同时报告等权买入持有基线；策略跑输也原样保留。
- 记录输入 SHA-256、Python、`bt`、`ffn`、pandas 和 worker 协议版本。
- 固定样本通过只说明该版本组合和接口通过，不说明策略有效。

## 尚未声称支持

真实行情复权、交易所日历、开盘成交、盘口和容量、市场冲击、部分成交、限价/止损订单、融资和借券、多币种现金、税费、实时交易及经验证收益。
