from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from broker import Broker


@dataclass
class Context:
    current_dt: dt.date | None = None


class BacktestEngine:
    def __init__(self, trade_days: List[dt.date], broker: Broker, strategy, data):
        self.trade_days = trade_days
        self.broker = broker
        self.strategy = strategy
        self.data = data
        self.context = Context()
        self.nav_records: List[Dict] = []
        self.signal_records: List[Dict] = []
        self.weight_records: List[Dict] = []

    def run(self, rebalance_freq: str = "M"):
        self.strategy.initialize(self.context)
        last_period = None
        for day in self.trade_days:
            self.context.current_dt = day
            self.strategy.before_trading_start(self.context)
            period_tag = day.strftime("%Y-%m") if rebalance_freq == "M" else day.strftime("%Y-%W") if rebalance_freq == "W" else str(day)
            do_rebalance = period_tag != last_period
            if do_rebalance:
                signals, weights = self.strategy.handle_data(self.context)
                self.signal_records.extend(signals)
                self.weight_records.extend(weights)
                self._rebalance(day, weights)
                last_period = period_tag
            self.strategy.after_trading_end(self.context)
            self._mark_to_market(day)

    def _rebalance(self, day: dt.date, weights: List[Dict]):
        weight_dict = {x["code"]: x["target_weight"] for x in weights}
        existing = set(self.broker.positions.keys())
        px_map = {}
        for code in set(weight_dict.keys()) | existing:
            close = self.data.get_close(code, day - dt.timedelta(days=5), day)
            if close.empty:
                continue
            px_map[code] = float(close.iloc[-1])
        nav = self.broker.nav(px_map)

        for code in existing - set(weight_dict.keys()):
            if code in px_map:
                self.broker.order_target_percent(day, code, 0.0, px_map[code], nav)
        for code, tw in weight_dict.items():
            if code in px_map:
                self.broker.order_target_percent(day, code, tw, px_map[code], nav)

    def _mark_to_market(self, day: dt.date):
        px_map = {}
        for code in self.broker.positions.keys():
            close = self.data.get_close(code, day - dt.timedelta(days=5), day)
            px_map[code] = float(close.iloc[-1]) if not close.empty else 0.0
        nav = self.broker.nav(px_map)
        self.nav_records.append({"date": day, "nav": nav, "cash": self.broker.cash, "positions": len(self.broker.positions)})

    def export(self, export_dir: str):
        pd.DataFrame(self.nav_records).to_csv(f"{export_dir}/daily_nav.csv", index=False)
        pd.DataFrame([f.__dict__ for f in self.broker.fills]).to_csv(f"{export_dir}/trades.csv", index=False)
        pd.DataFrame(self.signal_records).to_csv(f"{export_dir}/signals.csv", index=False)
        pd.DataFrame(self.weight_records).to_csv(f"{export_dir}/target_weights.csv", index=False)
