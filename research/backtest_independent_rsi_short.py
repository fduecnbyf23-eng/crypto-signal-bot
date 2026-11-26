#!/usr/bin/env python3
"""Independent, frozen validation of the 1H SWAP RSI-overbought reversal SHORT candidate."""
import argparse
import csv
import os

from indicator_features import build_features, apply_timeframe_scope
from backtest_frozen_indicators import read_csv, write_csv, funding_map, simulate, summarize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="independent-1h-data")
    ap.add_argument("--output-dir", default="independent-rsi-short-validation")
    args = ap.parse_args()
    all_trades, summaries = [], []
    for symbol in ["BTC", "ETH", "SOL", "BNB", "XRP"]:
        rows = read_csv(os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_1H.csv"))
        features = apply_timeframe_scope(build_features(rows), "1H")
        fmap, first_ts, last_ts, contiguous = funding_map(
            os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_funding.csv")
        )
        trades, invalid = simulate(
            rows, features, "1H", "never_true", "rsi_cross_down_70",
            "SWAP", symbol, "frozen_rsi_cross_down_70_short",
            "base", "independent_holdout", None, None,
            fmap, first_ts, contiguous
        )
        all_trades.extend(trades)
        summaries.append({
            "aggregation_level": "SYMBOL", "market": "SWAP", "symbol": symbol,
            "timeframe": "1H", "strategy": "rsi_cross_down_70_short",
            "exit_mode": "base", "period": "independent_holdout",
            "funding_first_utc": first_ts, "funding_last_utc": last_ts,
            **summarize(trades, invalid)
        })
    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid = sum(1 for t in all_trades if t["funding_valid"] is False)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "market": "SWAP", "symbol": "ALL",
        "timeframe": "1H", "strategy": "rsi_cross_down_70_short",
        "exit_mode": "base", "period": "independent_holdout",
        **summarize(all_trades, invalid)
    })
    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(os.path.join(args.output_dir, "trades.csv"), all_trades)
    write_csv(os.path.join(args.output_dir, "summary.csv"), summaries)
    print(f"INDEPENDENT_RSI_SHORT_COMPLETE trades_including_open={len(all_trades)} invalid_funding_trades={invalid}", flush=True)
    print("Fixed signal: RSI14 crosses down through 70; SHORT only; 1H SWAP; ATR14 stop 1.5x; target 2R.", flush=True)
    print("No parameters were tuned and no orders were generated.", flush=True)


if __name__ == "__main__":
    main()
