#!/usr/bin/env python3
"""Frozen independent 4H EMA + MACD SHORT replay. Research only; never places orders."""
import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from indicator_features import build_features, apply_timeframe_scope
from backtest_frozen_indicators import read_csv, write_csv, funding_map, simulate, summarize

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
START = int(datetime(2024, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2025, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
WARMUP_START = int(datetime(2024, 10, 17, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 3_600_000
FOUR_HOURS = 4 * HOUR
FUNDING_INTERVAL = 8 * HOUR


def aggregate_4h(hourly):
    if len(hourly) % 4:
        raise ValueError("Hourly data cannot be evenly aggregated into 4H candles")
    out = []
    for i in range(0, len(hourly), 4):
        group = hourly[i:i+4]
        stamps = [int(x["timestamp_ms"]) for x in group]
        if any(b-a != HOUR for a,b in zip(stamps, stamps[1:])):
            raise ValueError("Gap or duplicate inside 4H aggregation group")
        if stamps[0] % FOUR_HOURS:
            raise ValueError("Hourly candle is not aligned to UTC 4H boundary")
        out.append({
            "timestamp_ms": str(stamps[0]),
            "utc_time": group[0]["utc_time"],
            "open": group[0]["open"],
            "high": str(max(float(x["high"]) for x in group)),
            "low": str(min(float(x["low"]) for x in group)),
            "close": group[-1]["close"],
            "volume": str(sum(float(x["volume"]) for x in group)),
            "volume_currency": str(sum(float(x["volume_currency"]) for x in group)),
            "volume_quote": str(sum(float(x["volume_quote"]) for x in group)),
            "confirm": "1"
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warmup-dir", default="ema-macd-warmup")
    ap.add_argument("--test-dir", default="independent-1h-data")
    ap.add_argument("--output-dir", default="independent-ema-macd-short-2024-2025")
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    all_trades, summaries = [], []
    metadata = {
        "candidate_id": "OKX_SWAP_EMA_MACD_SHORT_4H_ALL5",
        "market": "SWAP", "timeframe": "4H", "direction": "SHORT",
        "window_start_inclusive_utc": "2024-11-26T00:00:00Z",
        "window_end_exclusive_utc": "2025-11-26T00:00:00Z",
        "warmup_start_utc": "2024-10-17T00:00:00Z",
        "signal": "On the same closed 4H candle: close < EMA20 < EMA50 < EMA200 AND MACD(12,26,9) bearish line/signal cross; enter next 4H open.",
        "execution": {
            "stop": "1.5 * signal-candle ATR14 from actual next-open entry",
            "target": "Fixed 2R",
            "same_candle_stop_target_priority": "STOP_FIRST",
            "one_open_position_per_symbol": True,
            "fee_per_side_pct": 0.05,
            "slippage_per_side_pct": 0.02,
            "funding": "Actual historical OKX SWAP funding; positive funding is received by SHORT.",
            "orders_generated": False
        },
        "data": {}
    }

    for symbol in SYMBOLS:
        warm_path = os.path.join(args.warmup_dir, f"{symbol}_USDT_SWAP_1H.csv")
        test_path = os.path.join(args.test_dir, f"{symbol}_USDT_SWAP_1H.csv")
        funding_path = os.path.join(args.test_dir, f"{symbol}_USDT_SWAP_funding.csv")
        warm = read_csv(warm_path)
        test = read_csv(test_path)
        warm_ts = [int(x["timestamp_ms"]) for x in warm]
        test_ts = [int(x["timestamp_ms"]) for x in test]
        if len(warm) != 960 or warm_ts[0] != WARMUP_START or warm_ts[-1] != START-HOUR:
            raise SystemExit(f"{symbol}: invalid 40-day warm-up window")
        if len(test) != 8760 or test_ts[0] != START or test_ts[-1] != END-HOUR:
            raise SystemExit(f"{symbol}: invalid 365-day independent test window")
        hourly = warm + test
        stamps = [int(x["timestamp_ms"]) for x in hourly]
        if any(b-a != HOUR for a,b in zip(stamps, stamps[1:])):
            raise SystemExit(f"{symbol}: combined hourly data has a gap or duplicate")
        bars = aggregate_4h(hourly)
        bar_ts = [int(x["timestamp_ms"]) for x in bars]
        if len(bars) != 2430 or bar_ts[0] != WARMUP_START or bar_ts[-1] != END-FOUR_HOURS:
            raise SystemExit(f"{symbol}: invalid 4H aggregate coverage")

        fmap, first_funding, last_funding, contiguous = funding_map(funding_path)
        expected_funding = list(range(START, END, FUNDING_INTERVAL))
        if sorted(fmap) != expected_funding or len(fmap) != 1095 or not contiguous:
            raise SystemExit(f"{symbol}: funding coverage failed independent audit")

        features = apply_timeframe_scope(build_features(bars), "4H")
        trades, invalid = simulate(
            bars, features, "4H", "never_true", "ema_macd_short",
            "SWAP", symbol, "ema_macd", "base", "independent_holdout",
            START + FOUR_HOURS, END, fmap, first_funding, contiguous
        )
        all_trades.extend(trades)
        summaries.append({
            "aggregation_level": "SYMBOL", "direction": "SHORT",
            "market": "SWAP", "symbol": symbol, "timeframe": "4H",
            "strategy": "ema_macd", "exit_mode": "base",
            "period": "independent_holdout",
            **summarize(trades, invalid)
        })
        metadata["data"][symbol] = {
            "warmup_hourly_candles": len(warm),
            "test_hourly_candles": len(test),
            "combined_hourly_candles": len(hourly),
            "combined_hourly_gaps": 0,
            "aggregated_4h_candles": len(bars),
            "funding_records": len(fmap),
            "funding_missing": 0,
            "funding_contiguous": contiguous,
            "invalid_funding_trades": invalid,
            "trades_including_open": len(trades),
            "closed_trades": sum(1 for t in trades if t["closed"]),
            "open_at_end": sum(1 for t in trades if not t["closed"])
        }

    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid_total = sum(1 for t in all_trades if t["funding_valid"] is False)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "direction": "SHORT",
        "market": "SWAP", "symbol": "ALL", "timeframe": "4H",
        "strategy": "ema_macd", "exit_mode": "base",
        "period": "independent_holdout",
        **summarize(all_trades, invalid_total)
    })

    monthly = defaultdict(list)
    for trade in all_trades:
        if trade["closed"]:
            monthly[(trade["symbol"], trade["exit_time_utc"][:7])].append(trade)
    monthly_rows = []
    for (symbol, month), group in sorted(monthly.items()):
        wins = [float(t["net_R"]) for t in group if float(t["net_R"]) > 0]
        losses = [float(t["net_R"]) for t in group if float(t["net_R"]) < 0]
        gross_loss = abs(sum(losses))
        monthly_rows.append({
            "symbol": symbol, "month_utc": month, "closed_trades": len(group),
            "wins": len(wins), "losses": len(losses),
            "net_R": round(sum(float(t["net_R"]) for t in group), 6),
            "profit_factor": round(sum(wins)/gross_loss, 6) if gross_loss else ("INF" if wins else "")
        })

    metadata["all_symbols"] = {
        "trades_including_open": len(all_trades),
        "closed_trades": sum(1 for t in all_trades if t["closed"]),
        "open_at_end": sum(1 for t in all_trades if not t["closed"]),
        "invalid_funding_trades": invalid_total,
        "funding_valid": invalid_total == 0,
        "data_valid": all(v["combined_hourly_gaps"] == 0 and
                          v["warmup_hourly_candles"] == 960 and
                          v["test_hourly_candles"] == 8760 and
                          v["aggregated_4h_candles"] == 2430 and
                          v["funding_records"] == 1095 and
                          v["funding_missing"] == 0 and v["funding_contiguous"]
                          for v in metadata["data"].values())
    }
    write_csv(os.path.join(args.output_dir, "trades.csv"), all_trades)
    write_csv(os.path.join(args.output_dir, "summary.csv"), summaries)
    write_csv(os.path.join(args.output_dir, "monthly_summary.csv"), monthly_rows)
    with open(os.path.join(args.output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")
    if not metadata["all_symbols"]["data_valid"] or not metadata["all_symbols"]["funding_valid"]:
        raise SystemExit("Independent EMA MACD archive/data audit failed")
    print(f"INDEPENDENT_EMA_MACD_SHORT_COMPLETE closed={metadata['all_symbols']['closed_trades']} open={metadata['all_symbols']['open_at_end']} invalid_funding={invalid_total}")
    print("Frozen EMA + MACD 4H SHORT replay complete. No parameter tuning; no orders generated.")


if __name__ == "__main__":
    main()
