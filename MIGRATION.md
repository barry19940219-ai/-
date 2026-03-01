# JoinQuant -> WindPy 本地化迁移说明

## 1) 聚宽依赖映射

| 聚宽对象/API | 本地替代 | WindPy 接口 |
|---|---|---|
| `get_price` 日线 | `WindDataAdapter.get_price_daily/get_close` | `w.wsd` |
| `get_trade_days` | `WindDataAdapter.get_trade_days` | `w.tdays` |
| `get_all_securities` | `WindDataAdapter.get_all_a_stocks` | `w.wset(sectorconstituent)` |
| `get_index_stocks` | `WindDataAdapter.get_index_stocks` | `w.wset(indexconstituent)` |
| `get_extras('is_st')` | `WindDataAdapter.get_st_flags` | `w.wss(riskwarning)` |
| `get_security_info` | `WindDataAdapter.get_security_basic` | `w.wss(sec_name, ipo_date, total_shares)` |
| `get_fundamentals(valuation.market_cap)` | `WindDataAdapter.get_market_cap` | `w.wss(ev)` + 兜底 |
| `get_fundamentals(income.profit_parent_company, statDate='ttm')` | `WindDataAdapter.get_profit_parent_ttm` | `w.wss(fa_profit_ttm)` |
| `get_industry(sw_l1)` | `WindDataAdapter.get_industry_sw_l1` | `w.wss(industry_sw)` |
| `order_target_percent` | `Broker.order_target_percent` | 本地撮合 |
| `run_daily/handle_data` | `BacktestEngine.run` 事件循环 | 本地调度 |

### 代码格式转换
- `000001.XSHE -> 000001.SZ`
- `600000.XSHG -> 600000.SH`
- 在 `WindDataAdapter.jq_to_wind / wind_to_jq` 统一封装。

## 2) 前复权统一口径
- 主流程统一 `PriceAdj=F`（前复权），由 `data_wind.py` 统一控制。
- 诊断脚本 `validate_alignment.py` 同时拉取 `PriceAdj=F` 和 `PriceAdj=N`，量化两种口径收益差。

## 3) 差异归因（聚宽原价 vs 前复权）
系统性差异来源：
1. 收益率序列：分红送转时，原价会出现价格跳变，前复权会平滑历史价格。
2. 均线/动量/RS：因历史价格重标定，阈值触发点会变化。
3. 撮合成交价：前复权成交会改变成交金额和份额，影响手续费与净值路径。

影响范围：
- 所有依赖价格与收益的因子（5/10/20日涨幅、MA、RS）
- 调仓清单和目标权重（通过筛选链路间接受影响）
- 最终回测净值、波动与回撤

## 4) 输出文件
- `output/daily_nav.csv`: 每日净值
- `output/trades.csv`: 成交记录
- `output/signals.csv`: 调仓日信号值
- `output/target_weights.csv`: 目标权重
- `output/qfq_vs_raw_diagnostics.csv`: 前复权/原价逐日差异
- `output/qfq_vs_raw_summary.csv`: 差异汇总
