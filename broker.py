from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Fill:
    date: dt.date
    code: str
    side: str
    qty: int
    price: float
    commission: float
    stamp_duty: float


class Broker:
    def __init__(self, initial_cash: float, commission_rate: float, stamp_duty_rate: float, slippage_bp: float):
        self.cash = initial_cash
        self.positions: Dict[str, int] = {}
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage = slippage_bp / 10000.0
        self.fills: List[Fill] = []

    def order_target_percent(self, date: dt.date, code: str, target_weight: float, px: float, nav: float):
        target_value = nav * target_weight
        current_qty = self.positions.get(code, 0)
        current_value = current_qty * px
        delta_value = target_value - current_value
        delta_qty = int(delta_value // px)
        if delta_qty == 0:
            return
        self._execute(date, code, delta_qty, px)

    def _execute(self, date: dt.date, code: str, qty: int, ref_price: float):
        side = "BUY" if qty > 0 else "SELL"
        exec_price = ref_price * (1 + self.slippage if qty > 0 else 1 - self.slippage)
        amount = abs(qty) * exec_price
        commission = max(amount * self.commission_rate, 5)
        stamp = amount * self.stamp_duty_rate if qty < 0 else 0
        if qty > 0:
            total_cost = amount + commission
            if total_cost > self.cash:
                qty = int((self.cash - 5) // exec_price)
                if qty <= 0:
                    return
                amount = qty * exec_price
                commission = max(amount * self.commission_rate, 5)
                stamp = 0
                total_cost = amount + commission
            self.cash -= total_cost
        else:
            self.cash += amount - commission - stamp
        self.positions[code] = self.positions.get(code, 0) + qty
        if self.positions[code] == 0:
            self.positions.pop(code)
        self.fills.append(Fill(date, code, side, abs(qty), exec_price, commission, stamp))

    def nav(self, price_map: Dict[str, float]) -> float:
        pos_val = sum(qty * price_map.get(code, 0) for code, qty in self.positions.items())
        return self.cash + pos_val
