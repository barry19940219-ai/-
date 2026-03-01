from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class Config:
    ENABLE_VOL_PRICE_FILTER: bool = True
    ENABLE_BOTTOM_VOL_FILTER: bool = True
    ENABLE_RS_FILTER: bool = True
    BOTTOM_VOL_RATIO: float = 1.3
    ENABLED_MA_PERIODS: tuple = (5,)
    SELECT_NUM: dict = None
    RS_CYCLE: int = 14
    NEW_STOCK_DAYS: int = 30
    ENABLE_SHORT_TERM_RISE_FILTER: bool = True
    SHORT_TERM_RISE_THRESHOLD: float = 0.2
    ENABLE_10D_RISE_FILTER: bool = True
    RISE_10D_THRESHOLD: float = 0.2
    PE_QUERY_BACK_DAYS: int = 60
    PE_DEFAULT_VALUE: float = -999
    LOSS_VALUE: float = -998
    BASE_INDEX: dict = None
    HSTECH_STOCKS: tuple = (
        "0700.HK", "9998.HK", "9888.HK", "3690.HK", "1810.HK",
        "9618.HK", "1024.HK", "2015.HK", "2382.HK", "3888.HK"
    )

    def __post_init__(self):
        if self.SELECT_NUM is None:
            self.SELECT_NUM = {
                "沪深300": 3, "中证500": 5, "中证1000": 5, "中证2000": 5,
                "恒生科技": 3, "上证红利": 3, "万得最小市值": 8, "全市场": 10
            }
        if self.BASE_INDEX is None:
            self.BASE_INDEX = {
                "沪深300": "000300.XSHG", "中证500": "000905.XSHG", "中证1000": "000852.XSHG",
                "中证2000": "000907.XSHG", "恒生科技": "HSTECH.HK", "上证红利": "000015.XSHG",
                "万得最小市值": "884149.WI", "全市场": "000300.XSHG"
            }
        self.STOCK_CODE_PATTERN = re.compile(r"^\d{5,6}\.(XSHE|XSHG|HK|WI)$")
        self.LATEST_TRADING_DAY = None


class CacheManager:
    def __init__(self):
        self.cache = {
            "vol_price_data": {}, "st_status": {}, "stock_names": {}, "ma_data": {},
            "daily_rise": {}, "rise_5d": {}, "rise_10d": {}, "rise_20d": {},
            "pe_ttm": {}, "sw_l1_industry": {}, "market_cap": {}, "list_date": {}, "latest_price": {},
            "base_pool": []
        }

    def get(self, cache_key: str, sub_key: str = None):
        if sub_key is not None:
            return self.cache.get(cache_key, {}).get(sub_key)
        return self.cache.get(cache_key)

    def set(self, cache_key: str, value, sub_key: str = None):
        if sub_key is not None:
            self.cache.setdefault(cache_key, {})[sub_key] = value
        else:
            self.cache[cache_key] = value

    def clear(self):
        for k in self.cache.keys():
            self.cache[k] = {} if isinstance(self.cache[k], dict) else []


class StockUtils:
    def __init__(self, config: Config, cache: CacheManager, data):
        self.c = config
        self.ca = cache
        self.data = data

    def get_valid_trading_days(self, end_day: datetime.date, back_days: int) -> List[datetime.date]:
        start_day = end_day - timedelta(days=back_days)
        days = self.data.get_trade_days(start_day, end_day)
        return days[::-1]

    def is_valid_stock_code(self, code: str) -> bool:
        return isinstance(code, str) and bool(self.c.STOCK_CODE_PATTERN.match(code))

    def get_stock_name(self, code: str) -> str:
        v = self.ca.get("stock_names", code)
        if v:
            return v
        basic = self.data.get_security_basic([code], self.c.LATEST_TRADING_DAY)
        name = basic.iloc[0]["name"] if not basic.empty else "未知"
        self.ca.set("stock_names", name, code)
        return name

    def get_latest_price(self, code: str) -> float:
        v = self.ca.get("latest_price", code)
        if v is not None:
            return v
        close = self.data.get_close(code, self.c.LATEST_TRADING_DAY - timedelta(days=5), self.c.LATEST_TRADING_DAY)
        val = float(close.iloc[-1]) if not close.empty else -999
        self.ca.set("latest_price", val, code)
        return val

    def get_daily_rise_rate(self, code: str) -> float:
        v = self.ca.get("daily_rise", code)
        if v is not None:
            return v
        close = self.data.get_close(code, self.c.LATEST_TRADING_DAY - timedelta(days=5), self.c.LATEST_TRADING_DAY)
        if len(close) < 2 or close.iloc[-2] <= 0:
            val = -999
        else:
            val = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2])
        self.ca.set("daily_rise", val, code)
        return val

    def get_rise_rate_by_days(self, code: str, days: int) -> float:
        cache_key = f"rise_{days}d"
        k = f"{code}_{days}d"
        v = self.ca.get(cache_key, k)
        if v is not None:
            return v
        close = self.data.get_close(code, self.c.LATEST_TRADING_DAY - timedelta(days=days + 40), self.c.LATEST_TRADING_DAY)
        if len(close) < days + 1 or close.iloc[-(days + 1)] <= 0:
            val = -999
        else:
            val = float((close.iloc[-1] - close.iloc[-(days + 1)]) / close.iloc[-(days + 1)])
        self.ca.set(cache_key, val, k)
        return val

    def get_rise_5d(self, code: str) -> float:
        return self.get_rise_rate_by_days(code, 5)

    def get_rise_10d(self, code: str) -> float:
        return self.get_rise_rate_by_days(code, 10)

    def get_rise_20d(self, code: str) -> float:
        return self.get_rise_rate_by_days(code, 20)

    def filter_short_term_rise_stocks(self, stock_list: List[str]) -> List[str]:
        if not self.c.ENABLE_SHORT_TERM_RISE_FILTER:
            return stock_list
        out = []
        for code in stock_list:
            rise_20d = self.get_rise_20d(code)
            if rise_20d == -999 or not (0 <= rise_20d <= self.c.SHORT_TERM_RISE_THRESHOLD):
                continue
            if self.c.ENABLE_10D_RISE_FILTER:
                rise_10d = self.get_rise_10d(code)
                if rise_10d == -999 or rise_10d > self.c.RISE_10D_THRESHOLD:
                    continue
            out.append(code)
        return out

    def get_market_cap(self, code: str) -> float:
        v = self.ca.get("market_cap", code)
        if v is not None:
            return v
        if ".HK" in code or ".WI" in code or not self.is_valid_stock_code(code):
            self.ca.set("market_cap", -999, code)
            return -999
        cap = round(self.data.get_market_cap(code, self.c.LATEST_TRADING_DAY), 2)
        self.ca.set("market_cap", cap, code)
        return cap

    def get_pe_ttm(self, code: str) -> float:
        v = self.ca.get("pe_ttm", code)
        if v is not None:
            return v
        if ".HK" in code or ".WI" in code or not self.is_valid_stock_code(code):
            self.ca.set("pe_ttm", self.c.PE_DEFAULT_VALUE, code)
            return self.c.PE_DEFAULT_VALUE
        market_cap = self.get_market_cap(code)
        if market_cap <= 0:
            self.ca.set("pe_ttm", self.c.PE_DEFAULT_VALUE, code)
            return self.c.PE_DEFAULT_VALUE
        profit_ttm = None
        for query_day in self.get_valid_trading_days(self.c.LATEST_TRADING_DAY, self.c.PE_QUERY_BACK_DAYS)[:10]:
            profit_ttm = self.data.get_profit_parent_ttm(code, query_day)
            if profit_ttm is not None:
                break
        if profit_ttm is None:
            self.ca.set("pe_ttm", self.c.PE_DEFAULT_VALUE, code)
            return self.c.PE_DEFAULT_VALUE
        if profit_ttm <= 0:
            self.ca.set("pe_ttm", self.c.LOSS_VALUE, code)
            return self.c.LOSS_VALUE
        pe = round(market_cap / profit_ttm, 2)
        self.ca.set("pe_ttm", pe, code)
        return pe

    def get_sw_l1_industry(self, code: str) -> str:
        v = self.ca.get("sw_l1_industry", code)
        if v is not None:
            return v
        if ".HK" in code or ".WI" in code or not self.is_valid_stock_code(code):
            return "无"
        ind = self.data.get_industry_sw_l1(code, self.c.LATEST_TRADING_DAY)
        self.ca.set("sw_l1_industry", ind, code)
        return ind

    def get_list_date(self, code: str) -> str:
        v = self.ca.get("list_date", code)
        if v is not None:
            return v
        basic = self.data.get_security_basic([code], self.c.LATEST_TRADING_DAY)
        val = "未知" if basic.empty or pd.isna(basic.iloc[0]["ipo_date"]) else basic.iloc[0]["ipo_date"].strftime("%Y-%m-%d")
        self.ca.set("list_date", val, code)
        return val


class DataLoader:
    def __init__(self, c: Config, ca: CacheManager, u: StockUtils, data):
        self.c, self.ca, self.u, self.data = c, ca, u, data

    def preload_vol_price_data(self, stock_list: List[str]):
        need_load = [x for x in stock_list if self.u.is_valid_stock_code(x) and self.ca.get("vol_price_data", x) is None]
        max_days = max(250, max(self.c.ENABLED_MA_PERIODS), 20)
        for code in need_load:
            df = self.data.get_price_daily(code, self.c.LATEST_TRADING_DAY - timedelta(days=max_days + 60), self.c.LATEST_TRADING_DAY, ["close", "volume"])
            if "date" not in df.columns:
                df = df.reset_index().rename(columns={"index": "date"})
            df = df.dropna().reset_index(drop=True)
            if df.empty:
                continue
            ma_data = {p: df["close"].rolling(p).mean().iloc[-1] for p in self.c.ENABLED_MA_PERIODS}
            vol_5d = df["volume"].iloc[-5:].mean() if len(df) >= 5 else 0
            vol_60d = df["volume"].iloc[-60:].mean() if len(df) >= 60 else 0
            df["vol_5d"] = vol_5d
            df["vol_60d"] = vol_60d
            self.ca.set("ma_data", ma_data, code)
            self.ca.set("vol_price_data", df, code)


class StockFilter:
    def __init__(self, c: Config, ca: CacheManager, u: StockUtils, l: DataLoader, data):
        self.c, self.ca, self.u, self.l, self.data = c, ca, u, l, data

    def get_base_stock_pool(self) -> List[str]:
        all_sec = self.data.get_all_a_stocks(self.c.LATEST_TRADING_DAY)
        valid_codes = [x for x in all_sec["code"].tolist() if self.u.is_valid_stock_code(x)]
        st_status = self.data.get_st_flags(valid_codes, self.c.LATEST_TRADING_DAY)
        non_st = [c for c in valid_codes if not st_status.get(c, False)]
        basic = self.data.get_security_basic(non_st, self.c.LATEST_TRADING_DAY).set_index("code")
        base_pool = []
        for code in non_st:
            ipo = basic.loc[code, "ipo_date"] if code in basic.index else None
            if ipo is not None and (self.c.LATEST_TRADING_DAY - ipo.date()).days >= self.c.NEW_STOCK_DAYS:
                base_pool.append(code)
        self.l.preload_vol_price_data(base_pool)
        final_pool = [c for c in base_pool if self.vol_price_filter_only(c) and self.bottom_vol_filter_only(c)]
        self.ca.set("base_pool", final_pool)
        return final_pool

    def vol_price_filter_only(self, code: str) -> bool:
        df = self.ca.get("vol_price_data", code)
        ma = self.ca.get("ma_data", code)
        if df is None or ma is None or df.empty:
            return False
        latest_close = df["close"].iloc[-1]
        for p in self.c.ENABLED_MA_PERIODS:
            if ma.get(p, 0) <= 0 or latest_close <= ma.get(p, 0):
                return False
        return True

    def bottom_vol_filter_only(self, code: str) -> bool:
        df = self.ca.get("vol_price_data", code)
        if df is None or df.empty:
            return False
        vol_60d = df["vol_60d"].iloc[-1]
        if vol_60d <= 0:
            return False
        return (df["vol_5d"].iloc[-1] / vol_60d) >= self.c.BOTTOM_VOL_RATIO

    def calculate_rs(self, stock_list: List[str], base_index: str) -> Dict[str, float]:
        start_day = self.c.LATEST_TRADING_DAY - timedelta(days=self.c.RS_CYCLE + 15)
        end_day = self.c.LATEST_TRADING_DAY
        try:
            base = self.data.get_close(base_index, start_day, end_day)
            base_return = (base.iloc[-1] / base.iloc[0]) - 1 if len(base) >= 2 else 0
        except Exception:
            base_return = 0
        rs = {}
        for code in stock_list:
            try:
                s = self.data.get_close(code, start_day, end_day)
                if len(s) < 2:
                    continue
                stock_return = (s.iloc[-1] / s.iloc[0]) - 1
                if base_return < 0 and stock_return < base_return - 0.1:
                    continue
                if base_return > 0 and stock_return < 0:
                    continue
                if stock_return < -0.2:
                    continue
                val = stock_return * 100 if abs(base_return) < 1e-6 else (stock_return / base_return if base_return > 0 else -stock_return / base_return)
                if val > 0:
                    rs[code] = val
            except Exception:
                continue
        if not rs:
            return {c: 50 for c in stock_list}
        mn, mx = min(rs.values()), max(rs.values())
        if mx - mn < 1e-6:
            return {k: 50 for k in rs}
        return {k: round((v - mn) / (mx - mn) * 100, 2) for k, v in rs.items()}


class StockSelector:
    def __init__(self, c: Config, ca: CacheManager, u: StockUtils, f: StockFilter, data):
        self.c, self.ca, self.u, self.f, self.data = c, ca, u, f, data

    def select_index(self, index_name: str) -> List[Tuple[str, float]]:
        if index_name == "恒生科技":
            index_stocks = list(self.c.HSTECH_STOCKS)
        elif index_name == "万得最小市值":
            return []
        else:
            index_stocks = self.data.get_index_stocks(self.c.BASE_INDEX[index_name], self.c.LATEST_TRADING_DAY)
        valid_stocks = index_stocks if index_name == "恒生科技" else [x for x in index_stocks if x in self.ca.get("base_pool")]
        if not valid_stocks:
            return []
        rs_dict = self.f.calculate_rs(valid_stocks, self.c.BASE_INDEX[index_name])
        filter_stocks = list(rs_dict.keys()) if index_name == "恒生科技" else self.u.filter_short_term_rise_stocks(list(rs_dict.keys()))
        top = sorted([(k, rs_dict[k]) for k in filter_stocks], key=lambda x: x[1], reverse=True)[: self.c.SELECT_NUM[index_name]]
        return top

    def select_all_market(self) -> List[Tuple[str, float]]:
        valid = self.ca.get("base_pool")
        rs_dict = self.f.calculate_rs(valid, self.c.BASE_INDEX["全市场"])
        filter_stocks = self.u.filter_short_term_rise_stocks(list(rs_dict.keys()))
        return sorted([(k, rs_dict[k]) for k in filter_stocks], key=lambda x: x[1], reverse=True)[: self.c.SELECT_NUM["全市场"]]


class Strategy:
    """保留 initialize/before_trading_start/handle_data/after_trading_end 结构。"""

    def __init__(self, data, target_bucket: str = "全市场"):
        self.data = data
        self.target_bucket = target_bucket
        self.c = Config()
        self.ca = CacheManager()
        self.u = StockUtils(self.c, self.ca, self.data)
        self.l = DataLoader(self.c, self.ca, self.u, self.data)
        self.f = StockFilter(self.c, self.ca, self.u, self.l, self.data)
        self.selector = StockSelector(self.c, self.ca, self.u, self.f, self.data)

    def initialize(self, context):
        return

    def before_trading_start(self, context):
        self.ca.clear()
        self.c.LATEST_TRADING_DAY = context.current_dt
        self.f.get_base_stock_pool()

    def handle_data(self, context):
        buckets = {
            "沪深300": self.selector.select_index("沪深300"),
            "中证500": self.selector.select_index("中证500"),
            "中证1000": self.selector.select_index("中证1000"),
            "中证2000": self.selector.select_index("中证2000"),
            "恒生科技": self.selector.select_index("恒生科技"),
            "上证红利": self.selector.select_index("上证红利"),
            "全市场": self.selector.select_all_market(),
        }
        selected = buckets.get(self.target_bucket, [])
        signals = []
        for name, items in buckets.items():
            for rank, (code, rs) in enumerate(items, 1):
                signals.append({"date": context.current_dt, "bucket": name, "rank": rank, "code": code, "signal_rs": rs})
        weights = []
        if selected:
            w = 1.0 / len(selected)
            for code, rs in selected:
                weights.append({"date": context.current_dt, "code": code, "target_weight": w, "signal_rs": rs, "bucket": self.target_bucket})
        return signals, weights

    def after_trading_end(self, context):
        return
