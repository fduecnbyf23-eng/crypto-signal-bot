#!/usr/bin/env python3
"""Independent frozen RSI+volume SHORT 1H SWAP validation; research only."""
import argparse
import csv
import json
import os

from indicator_features import build_features, apply_timeframe_scope
from backtest_frozen_indicators import read_csv, write_csv, funding_map, simulate, summarize

SYMBOLS = ["ETH", "SOL", "BNB", "XRP"]
START_MS = 1732579200000  # 2024-11-26 00:00:00 UTC


def validate_candles(rows, symbol):
    stamps = [int(r["timestamp_ms"]) for r in rows]
    if len(stamps) != 8760:
        raise ValueError(f"{symbol}: expected 8760 hourly candles, got {len(stamps)}")
    if stamps[0] != START_MS or stamps[-1] != START_MS + 8759 * 3600000:
        raise ValueError(f"{symbol}: unexpected independent-window endpoints")
    if any(b - a != 3600000 for a, b in zip(stamps, stamps[1:])):
        raise ValueError(f"{symbol}: hourly candle gap or duplicate")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="independent-1h-data")
    ap.add_argument("--output-dir", default="independent-rsi-volume-validation")
    args = ap.parse_args()
    all_trades, summaries = [], []
    for symbol in SYMBOLS:
        candle_path = os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_1H.csv")
        funding_path = os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_funding.csv")
        rows = read_csv(candle_path)
        validate_candles(rows, symbol)
        fmap, first_ts, last_ts, contiguous = funding_map(funding_path)
        if len(fmap) != 1095 or not contiguous:
            raise ValueError(f"{symbol}: expected 1095 contiguous funding records; got {len(fmap)}")
        features = apply_timeframe_scope(build_features(rows), "1H")
        # Frozen rule: (RSI cross down through 70 OR confirmed bearish divergence)
        # AND quote-volume >= 1.5x SMA20; SHORT only.
        # Frozen exit experiment: 1.5 ATR protective stop; exit at next candle open
        # after a closed candle RSI <= 30. No fixed profit target.
        trades, invalid = simulate(
            rows, features, "1H", "never_true", "rsi_volume_short",
            "SWAP", symbol, "rsi_volume_short",
            "rsi_extreme", "independent_2024_2025", None, None,
            fmap, first_ts, contiguous
        )
        all_trades.extend(trades)
        summaries.append({
            "aggregation_level": "SYMBOL", "market": "SWAP", "symbol": symbol,
            "timeframe": "1H", "direction": "SHORT", "strategy": "rsi_volume_short",
            "exit_mode": "rsi_extreme", "period": "independent_2024_2025",
            "candles": len(rows), "funding_records": len(fmap),
            "funding_first_utc": first_ts, "funding_last_utc": last_ts,
            **summarize(trades, invalid)
        })
    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid = sum(1 for t in all_trades if t["funding_valid"] is False)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "market": "SWAP", "symbol": "ALL",
        "timeframe": "1H", "direction": "SHORT", "strategy": "rsi_volume_short",
        "exit_mode": "rsi_extreme", "period": "independent_2024_2025",
        **summarize(all_trades, invalid)
    })
    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(os.path.join(args.output_dir, "trades.csv"), all_trades)
    write_csv(os.path.join(args.output_dir, "summary.csv"), summaries)
    metadata = {
        "candidate_id": "OKX_SWAP_RSI_VOLUME_SHORT_1H_EXIT_RSI30_ETH_SOL_BNB_XRP",
        "window_start_utc_inclusive": "2024-11-26T00:00:00Z",
        "window_end_utc_exclusive": "2025-11-26T00:00:00Z",
        "symbols": SYMBOLS, "market": "OKX USDT-SWAP", "timeframe": "1H",
        "signal": "(RSI14 cross down through 70 OR confirmed bearish RSI divergence) AND quote_volume >= 1.5 * SMA20 quote_volume",
        "entry": "next 1H candle open",
        "exit": "protective stop 1.5 * ATR14; no fixed target; after closed candle RSI14 <= 30 exit at next candle open",
        "costs_per_side": {"taker_fee_pct": 0.05, "slippage_pct": 0.02},
        "funding": "historical OKX funding, strictly after entry through exit; positive funding received by SHORT",
        "no_parameter_changes": True, "no_orders_generated": True
    }
    with open(os.path.join(args.output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"INDEPENDENT_RSI_VOLUME_COMPLETE symbols={len(SYMBOLS)} trades_including_open={len(all_trades)} invalid_funding_trades={invalid}", flush=True)


if __name__ == "__main__":
    main()
