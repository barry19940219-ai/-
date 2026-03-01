from __future__ import annotations

import datetime as dt
from typing import List

from data_wind import WindDataAdapter


class WindCalendar:
    def __init__(self, data: WindDataAdapter):
        self.data = data

    def get_trade_days(self, start_date: dt.date, end_date: dt.date) -> List[dt.date]:
        return self.data.get_trade_days(start_date, end_date)

    def is_trade_day(self, date: dt.date) -> bool:
        days = self.get_trade_days(date, date)
        return len(days) == 1 and days[0] == date
