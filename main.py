from __future__ import annotations

import argparse
import datetime as dt
import os

import pandas as pd
import yaml

from broker import Broker
from calendar_wind import WindCalendar
from data_wind import WindConfig, WindDataAdapter
from engine import BacktestEngine
from strategy import Strategy


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    return ap.parse_args()


def run(cfg):
    os.makedirs(cfg["backtest"]["export_dir"], exist_ok=True)
    data = WindDataAdapter(WindConfig(
        price_adjust=cfg["wind"]["price_adjust"],
        start_timeout=cfg["wind"].get("start_timeout", 15),
        start_retry_interval=cfg["wind"].get("start_retry_interval", 0.5),
    ))
    data.start()
    cal = WindCalendar(data)
    start = dt.date.fromisoformat(cfg["backtest"]["start_date"])
    end = dt.date.fromisoformat(cfg["backtest"]["end_date"])
    days = cal.get_trade_days(start, end)

    broker = Broker(
        initial_cash=cfg["backtest"]["initial_cash"],
        commission_rate=cfg["backtest"]["commission_rate"],
        stamp_duty_rate=cfg["backtest"]["stamp_duty_rate"],
        slippage_bp=cfg["backtest"]["slippage_bp"],
    )
    strat = Strategy(data, target_bucket=cfg["strategy"]["target_bucket"])
    engine = BacktestEngine(days, broker, strat, data)
    if cfg["strategy"].get("enable_trade_simulation", True):
        engine.run(rebalance_freq=cfg["backtest"]["rebalance_freq"])
    else:
        engine.run(rebalance_freq="Z")
    engine.export(cfg["backtest"]["export_dir"])

    nav = pd.DataFrame(engine.nav_records)
    bench = data.get_close("000300.XSHG", start, end)
    if not bench.empty:
        bench_nav = bench / bench.iloc[0]
        bench_nav.to_csv(f"{cfg['backtest']['export_dir']}/benchmark_nav.csv")
    nav.to_csv(f"{cfg['backtest']['export_dir']}/daily_nav.csv", index=False)
    print(f"回测完成，输出目录: {cfg['backtest']['export_dir']}")


if __name__ == "__main__":
    args = parse_args()
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    run(cfg)
