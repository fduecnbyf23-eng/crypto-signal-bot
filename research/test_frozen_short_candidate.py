#!/usr/bin/env python3
"""One-shot frozen SHORT candidate validation. Research only; never places orders."""
import argparse
import json
from datetime import datetime, timezone

import short_strategy_experiments as study

TEST_START = "2025-08-25T00:00:00Z"
TEST_END = "2025-11-23T00:00:00Z"  # exclusive
CONFIG = {"adx_min": 25, "rsi_max": 50, "stop_atr": 2.0, "rr": 2.5}

def to_ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research-data")
    ap.add_argument("--out", default="research-results")
    args = ap.parse_args()

    data, meta, first_ts, last_ts = study.load_data(args.data)
    start_ts, end_ts = to_ms(TEST_START), to_ms(TEST_END)
    if first_ts > start_ts - 14 * 24 * 60 * 60 * 1000:
        raise RuntimeError("Insufficient warmup: need at least 14 days before test start")
    if last_ts < end_ts - 15 * 60 * 1000:
        raise RuntimeError("Downloaded candles do not cover the full frozen test window")

    result = study.replay(data, CONFIG, start_ts, end_ts)
    original_symbols = study.SYMBOLS
    per_symbol = {}
    try:
        for symbol in original_symbols:
            study.SYMBOLS = [symbol]
            per_symbol[symbol] = study.replay(data, CONFIG, start_ts, end_ts)
    finally:
        study.SYMBOLS = original_symbols

    report = {
        "candidate": "Frozen SHORT-only candidate",
        "parameters": CONFIG,
        "test_start_utc_inclusive": TEST_START,
        "test_end_utc_exclusive": TEST_END,
        "warmup_start_utc": datetime.fromtimestamp(first_ts / 1000, timezone.utc).isoformat(),
        "method": "SHORT only; all five original filters required (MTF, ADX>=18, volume, S/R room, ATR regime), then ADX>=25 and RSI<=50; entry at next 15m open; stop 2 ATR; target 2.5R; one open position per symbol; daily cap 15 entries; stop-first on same-candle stop/target; open positions excluded from closed-trade metrics.",
        "costs_and_funding": "0.05% fee and 0.02% slippage per side; historical OKX funding applied where records exist. These are assumptions, not guaranteed fills or account-specific fees.",
        "data": meta,
        "overall": result,
        "per_symbol": per_symbol,
        "decision_rule": "Exploratory independent historical validation only. Do not promote to paper trading unless results are positive after costs/funding, reasonably distributed across symbols, and followed by a separate forward paper-trading test."
    }
    import os
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "frozen_short_candidate_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "frozen_short_candidate_report.md"), "w", encoding="utf-8") as f:
        f.write("# Frozen SHORT candidate validation (research only)\\n\\n")
        f.write(f"Test: {TEST_START} to {TEST_END} (end exclusive).\\n\\n")
        f.write(f"Parameters: ADX >= {CONFIG['adx_min']}, RSI <= {CONFIG['rsi_max']}, SL {CONFIG['stop_atr']} ATR, TP {CONFIG['rr']}R.\\n\\n")
        f.write("| Scope | Closed trades | Win rate | Net R | Profit factor |\\n|---|---:|---:|---:|---:|\\n")
        for label, m in [("All symbols", result), *per_symbol.items()]:
            f.write(f"| {label} | {m['closed']} | {m['win_rate_pct']:.2f}% | {m['net_R']:.2f} | {m['profit_factor'] if m['profit_factor'] is not None else 'n/a'} |\\n")
        f.write("\\nResearch only. No live orders or bot changes.\\n")
    print(json.dumps({"overall": result, "per_symbol": per_symbol}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
