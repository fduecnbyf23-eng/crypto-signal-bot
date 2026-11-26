#!/usr/bin/env python3
"""Independent frozen replay of OKX SWAP 1H VWAP + EMA SHORT candidates. No orders."""
import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from indicator_features import build_features, apply_timeframe_scope
from backtest_frozen_indicators import read_csv, write_csv, funding_map, simulate, summarize

START_UTC = "2024-11-26T00:00:00Z"
END_UTC = "2025-11-26T00:00:00Z"
START_MS = int(datetime(2024, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2025, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="independent-1h-data")
    ap.add_argument("--output-dir", default="independent-vwap-ema-short")
    args = ap.parse_args()

    all_trades, summaries = [], []
    audit = {"candidate_id": "OKX_SWAP_VWAP_EMA_SHORT_1H_ALL5",
             "market": "SWAP", "timeframe": "1H", "direction": "SHORT",
             "window_start_inclusive_utc": START_UTC,
             "window_end_exclusive_utc": END_UTC,
             "signal": "UTC VWAP short bounce AND bearish EMA20/50/200 stack on the same closed 1H candle; enter next 1H open.",
             "execution": {"stop": "1.5 * signal-candle ATR14 from actual entry",
                           "target": "2R", "same_candle_priority": "STOP_FIRST",
                           "fee_per_side_pct": 0.05, "slippage_per_side_pct": 0.02,
                           "funding": "Actual historical OKX funding; positive funding received by SHORT.",
                           "orders_generated": False},
             "instruments": {}}

    for symbol in SYMBOLS:
        candle_path = os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_1H.csv")
        funding_path = os.path.join(args.input_dir, f"{symbol}_USDT_SWAP_funding.csv")
        rows = read_csv(candle_path)
        stamps = [int(r["timestamp_ms"]) for r in rows]
        if len(rows) != 8760:
            raise SystemExit(f"{symbol}: expected 8760 hourly candles, got {len(rows)}")
        if stamps[0] != START_MS or stamps[-1] != END_MS - 3600000:
            raise SystemExit(f"{symbol}: unexpected candle window {stamps[0]}..{stamps[-1]}")
        if any(b - a != 3600000 for a, b in zip(stamps, stamps[1:])):
            raise SystemExit(f"{symbol}: hourly candle gap or duplicate detected")

        fmap, first_ts, last_ts, contiguous = funding_map(funding_path)
        if len(fmap) != 1095 or not contiguous:
            raise SystemExit(f"{symbol}: expected 1095 contiguous 8-hour funding records; got {len(fmap)}, contiguous={contiguous}")

        features = apply_timeframe_scope(build_features(rows), "1H")
        trades, invalid = simulate(
            rows, features, "1H", "never_true", "vwap_ema_short",
            "SWAP", symbol, "vwap_ema_short", "base",
            "independent_holdout", None, None, fmap, first_ts, contiguous
        )
        all_trades.extend(trades)
        summaries.append({
            "aggregation_level": "SYMBOL", "market": "SWAP", "symbol": symbol,
            "timeframe": "1H", "strategy": "vwap_ema_short", "exit_mode": "base",
            "period": "independent_holdout",
            "funding_first_utc": datetime.fromtimestamp(first_ts / 1000, timezone.utc).isoformat(),
            "funding_last_utc": datetime.fromtimestamp(last_ts / 1000, timezone.utc).isoformat(),
            **summarize(trades, invalid)
        })
        audit["instruments"][symbol] = {
            "hourly_candles": len(rows), "candle_gaps": 0,
            "funding_records": len(fmap), "funding_contiguous": contiguous,
            "invalid_funding_trades": invalid,
            "closed_trades": sum(1 for t in trades if t["closed"]),
            "open_at_end": sum(1 for t in trades if not t["closed"])
        }

    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid_total = sum(1 for t in all_trades if t["funding_valid"] is False)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "market": "SWAP", "symbol": "ALL",
        "timeframe": "1H", "strategy": "vwap_ema_short", "exit_mode": "base",
        "period": "independent_holdout",
        **summarize(all_trades, invalid_total)
    })

    monthly = defaultdict(list)
    for t in all_trades:
        if t["closed"]:
            month = t["exit_time_utc"][:7]
            monthly[(t["symbol"], month)].append(t)
    monthly_rows = []
    for (symbol, month), group in sorted(monthly.items()):
        net = sum(float(t["net_R"]) for t in group)
        wins = sum(float(t["net_R"]) > 0 for t in group)
        losses = sum(float(t["net_R"]) < 0 for t in group)
        gross_profit = sum(float(t["net_R"]) for t in group if float(t["net_R"]) > 0)
        gross_loss = abs(sum(float(t["net_R"]) for t in group if float(t["net_R"]) < 0))
        monthly_rows.append({
            "symbol": symbol, "month_utc": month, "closed_trades": len(group),
            "wins": wins, "losses": losses, "net_R": round(net, 6),
            "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else ("INF" if gross_profit else "")
        })

    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(os.path.join(args.output_dir, "trades.csv"), all_trades)
    write_csv(os.path.join(args.output_dir, "summary.csv"), summaries)
    write_csv(os.path.join(args.output_dir, "monthly_summary.csv"), monthly_rows)
    audit["total_trades_including_open"] = len(all_trades)
    audit["invalid_funding_trades"] = invalid_total
    audit["funding_valid"] = invalid_total == 0
    audit["data_valid"] = all(v["hourly_candles"] == 8760 and v["candle_gaps"] == 0 and
                              v["funding_records"] == 1095 and v["funding_contiguous"] and
                              v["invalid_funding_trades"] == 0 for v in audit["instruments"].values())
    with open(os.path.join(args.output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
        f.write("\n")
    if not audit["data_valid"]:
        raise SystemExit("Independent VWAP EMA archive/data audit failed")
    print(f"INDEPENDENT_VWAP_EMA_SHORT_COMPLETE trades_including_open={len(all_trades)} invalid_funding={invalid_total}")
    print("Frozen VWAP + EMA SHORT replay complete. No parameters tuned; no orders generated.")


if __name__ == "__main__":
    main()
