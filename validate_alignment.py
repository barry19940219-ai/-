from __future__ import annotations

import argparse
import datetime as dt
import os

import pandas as pd
import yaml

from data_wind import WindConfig, WindDataAdapter


def compare_price_impact(data_f: WindDataAdapter, data_n: WindDataAdapter, code: str, start: dt.date, end: dt.date):
    pf = data_f.get_close(code, start, end)
    pn = data_n.get_close(code, start, end)
    df = pd.DataFrame({"qfq_close": pf, "raw_close": pn}).dropna()
    df["qfq_ret"] = df["qfq_close"].pct_change()
    df["raw_ret"] = df["raw_close"].pct_change()
    df["ret_diff"] = df["qfq_ret"] - df["raw_ret"]
    return df


def main(cfg_path: str):
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    out = cfg["backtest"]["export_dir"]
    os.makedirs(out, exist_ok=True)
    start = dt.date.fromisoformat(cfg["backtest"]["start_date"])
    end = dt.date.fromisoformat(cfg["backtest"]["end_date"])

    data_f = WindDataAdapter(WindConfig(price_adjust="F"))
    data_n = WindDataAdapter(WindConfig(price_adjust="N"))
    data_f.start(); data_n.start()

    sample_codes = ["000300.XSHG", "000001.XSHE", "600519.XSHG"]
    all_df = []
    for code in sample_codes:
        d = compare_price_impact(data_f, data_n, code, start, end)
        d["code"] = code
        all_df.append(d.reset_index().rename(columns={"index": "date"}))
    merged = pd.concat(all_df, ignore_index=True)
    merged.to_csv(f"{out}/qfq_vs_raw_diagnostics.csv", index=False)

    summary = merged.groupby("code")["ret_diff"].agg(["mean", "std", "max", "min"]).reset_index()
    summary.to_csv(f"{out}/qfq_vs_raw_summary.csv", index=False)
    print("诊断完成：qfq_vs_raw_diagnostics.csv / qfq_vs_raw_summary.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    main(args.config)
