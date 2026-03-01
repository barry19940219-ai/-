from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
from WindPy import w


@dataclass
class WindConfig:
    price_adjust: str = "F"  # F=前复权, N=不复权, B=后复权


class WindDataAdapter:
    """WindPy 统一数据适配层：所有行情与撮合价格统一走前复权（F）。"""

    def __init__(self, config: WindConfig):
        self.config = config
        self._cache: Dict[str, pd.DataFrame | pd.Series | dict] = {}

    @staticmethod
    def jq_to_wind(code: str) -> str:
        if code.endswith(".XSHG"):
            return code.replace(".XSHG", ".SH")
        if code.endswith(".XSHE"):
            return code.replace(".XSHE", ".SZ")
        return code

    @staticmethod
    def wind_to_jq(code: str) -> str:
        if code.endswith(".SH"):
            return code.replace(".SH", ".XSHG")
        if code.endswith(".SZ"):
            return code.replace(".SZ", ".XSHE")
        return code

    def start(self) -> None:
        if not w.isconnected():
            ret = w.start()
            if ret.ErrorCode != 0:
                raise RuntimeError(f"Wind 启动失败: {ret.ErrorCode} {ret.Data}")

    def _wsd(self, codes: Sequence[str] | str, fields: str, start: dt.date | str, end: dt.date | str,
             extra: Optional[str] = None):
        options = [f"PriceAdj={self.config.price_adjust}"]
        if extra:
            options.append(extra)
        opt = ";".join(options)
        ret = w.wsd(codes, fields, str(start), str(end), opt)
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.wsd失败: {ret.ErrorCode} {fields} {codes}")
        return ret

    def get_trade_days(self, start_date: dt.date, end_date: dt.date) -> List[dt.date]:
        key = f"trade_days:{start_date}:{end_date}"
        if key in self._cache:
            return list(self._cache[key])
        ret = w.tdays(str(start_date), str(end_date), "")
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.tdays失败: {ret.ErrorCode}")
        days = [d.date() for d in ret.Data[0]]
        self._cache[key] = days
        return days

    def get_latest_trade_day(self, end_date: dt.date) -> dt.date:
        days = self.get_trade_days(end_date - dt.timedelta(days=30), end_date)
        if not days:
            raise RuntimeError("未获取到交易日")
        return days[-1]

    def get_price_daily(self, codes: Sequence[str] | str, start_date: dt.date, end_date: dt.date,
                        fields: Sequence[str]) -> pd.DataFrame:
        codes_key = ",".join(codes) if isinstance(codes, (list, tuple)) else str(codes)
        field_key = ",".join(fields)
        key = f"wsd:{codes_key}:{field_key}:{start_date}:{end_date}:adj={self.config.price_adjust}"
        if key in self._cache:
            return self._cache[key].copy()
        if isinstance(codes, str):
            wind_code = self.jq_to_wind(codes)
            ret = self._wsd(wind_code, field_key, start_date, end_date)
            data = pd.DataFrame({f: ret.Data[idx] for idx, f in enumerate(fields)}, index=pd.to_datetime(ret.Times))
            data["code"] = codes
            data.index.name = "date"
            self._cache[key] = data
            return data.copy()

        frames: List[pd.DataFrame] = []
        for code in codes:
            single = self.get_price_daily(code, start_date, end_date, fields)
            if "date" in single.columns:
                df = single.copy()
            else:
                df = single.reset_index().rename(columns={"index": "date"})
            frames.append(df)
        merged = pd.concat(frames, ignore_index=True)
        self._cache[key] = merged
        return merged.copy()

    def get_close(self, code: str, start_date: dt.date, end_date: dt.date) -> pd.Series:
        df = self.get_price_daily(code, start_date, end_date, ["close"])
        if "date" in df.columns:
            s = pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
            s.index.name = "date"
            return s.dropna()
        return df["close"].dropna()

    def get_all_a_stocks(self, date: dt.date) -> pd.DataFrame:
        key = f"all_a:{date}"
        if key in self._cache:
            return self._cache[key].copy()
        ret = w.wset("sectorconstituent", f"date={date};sectorid=a001010100000000")
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.wset sectorconstituent失败: {ret.ErrorCode}")
        df = pd.DataFrame(ret.Data, index=ret.Fields).T
        # Wind 回传字段通常包含 wind_code, sec_name
        df = df.rename(columns={"wind_code": "wind_code", "sec_name": "display_name"})
        df["code"] = df["wind_code"].map(self.wind_to_jq)
        self._cache[key] = df
        return df.copy()

    def get_index_stocks(self, index_code: str, date: dt.date) -> List[str]:
        wind_index = self.jq_to_wind(index_code)
        ret = w.wset("indexconstituent", f"date={date};windcode={wind_index}")
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.wset indexconstituent失败: {ret.ErrorCode}")
        df = pd.DataFrame(ret.Data, index=ret.Fields).T
        if "wind_code" not in df.columns:
            return []
        return [self.wind_to_jq(c) for c in df["wind_code"].tolist()]

    def get_st_flags(self, codes: Sequence[str], date: dt.date) -> Dict[str, bool]:
        if not codes:
            return {}
        wind_codes = [self.jq_to_wind(c) for c in codes]
        ret = w.wss(wind_codes, "riskwarning", f"tradeDate={date}")
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.wss riskwarning失败: {ret.ErrorCode}")
        vals = ret.Data[0]
        out = {}
        for i, wc in enumerate(ret.Codes):
            out[self.wind_to_jq(wc)] = bool(vals[i])
        return out

    def get_security_basic(self, codes: Sequence[str], date: dt.date) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame(columns=["code", "name", "ipo_date", "total_shares"])
        wind_codes = [self.jq_to_wind(c) for c in codes]
        ret = w.wss(wind_codes, "sec_name,ipo_date,total_shares", f"tradeDate={date}")
        if ret.ErrorCode != 0:
            raise RuntimeError(f"w.wss sec_name失败: {ret.ErrorCode}")
        df = pd.DataFrame({
            "wind_code": ret.Codes,
            "name": ret.Data[0],
            "ipo_date": ret.Data[1],
            "total_shares": ret.Data[2],
        })
        df["code"] = df["wind_code"].map(self.wind_to_jq)
        return df[["code", "name", "ipo_date", "total_shares"]]

    def get_market_cap(self, code: str, date: dt.date) -> float:
        wc = self.jq_to_wind(code)
        ret = w.wss(wc, "ev", f"tradeDate={date}")
        if ret.ErrorCode == 0 and ret.Data and ret.Data[0][0] is not None:
            ev = ret.Data[0][0]
            if pd.notna(ev):
                return float(ev) / 1e8  # 元 -> 亿
        # 兜底：close * total_shares
        basic = self.get_security_basic([code], date)
        close = self.get_close(code, date - dt.timedelta(days=10), date)
        if close.empty or basic.empty or pd.isna(basic.iloc[0]["total_shares"]):
            return -999
        return float(close.iloc[-1] * basic.iloc[0]["total_shares"] / 1e8)

    def get_profit_parent_ttm(self, code: str, date: dt.date) -> Optional[float]:
        wc = self.jq_to_wind(code)
        ret = w.wss(wc, "fa_profit_ttm", f"tradeDate={date};rptType=1")
        if ret.ErrorCode != 0:
            return None
        val = ret.Data[0][0]
        if val is None or pd.isna(val):
            return None
        return float(val) / 1e8  # 元 -> 亿

    def get_industry_sw_l1(self, code: str, date: dt.date) -> str:
        wc = self.jq_to_wind(code)
        ret = w.wss(wc, "indexcode_sw,industry_sw", f"tradeDate={date};industryType=1")
        if ret.ErrorCode != 0:
            return "无"
        val = ret.Data[1][0] if len(ret.Data) > 1 else None
        return str(val) if val else "无"
