#!/usr/bin/env python3
"""Single, frozen out-of-sample test of the previously selected all_filters candidate."""
import argparse, csv, json, os
from datetime import datetime
import backtest_strategy as bt
import research_ema_filters as study

WARMUP_START = "2025-08-11T00:00:00+00:00"
TEST_START = "2025-08-25T00:00:00+00:00"
TEST_END = "2025-11-23T00:00:00+00:00"  # exclusive

def ms(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()*1000)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research-data")
    ap.add_argument("--out", default="research-results")
    args = ap.parse_args()
    start_ms, end_ms = ms(TEST_START), ms(TEST_END)
    data, meta = study.build_data(args.data)
    filters = study.VARIANTS["all_filters"]
    metrics, trades, candidate_counts = study.run_variant(data, start_ms, end_ms, filters)
    per_symbol = {
        symbol: bt.summarize([t for t in trades if t["symbol"] == symbol])
        for symbol in bt.SYMBOLS
    }
    per_direction = {
        direction: bt.summarize([t for t in trades if t["direction"] == direction])
        for direction in ("LONG", "SHORT")
    }
    os.makedirs(args.out, exist_ok=True)
    report = {
        "status": "completed_single_candidate_test",
        "candidate": "all_filters",
        "selection_note": "Only the previously selected all_filters candidate was tested. No alternative variants, parameter search, threshold changes, or retuning were performed.",
        "market": "OKX USDT perpetual SWAP",
        "warmup_start_utc": WARMUP_START,
        "test_start_utc_inclusive": TEST_START,
        "test_end_utc_exclusive": TEST_END,
        "frozen_baseline": "15m close above/below EMA50; RSI14 LONG 52-68 / SHORT 32-48; volume greater than 1.2x the mean of the previous 20 closed 15m candles.",
        "frozen_filters": study.FILTERS,
        "applied_filter_keys": filters,
        "method": "Closed 15m signal, next 15m open entry; one open position per symbol; maximum 15 new entries per UTC day; ATR stop 1.5x and target 2R; stop assumed first if SL and TP are both touched in one candle; positions still open at period end are marked to close and excluded from closed-trade PF.",
        "costs": "0.05% fee and 0.02% slippage per side, plus OKX historical funding records where available.",
        "caveats": "Simulation only, not actual fills. Approximate drawdown is a compounded-R estimate and does not model correlated exposure, overlapping portfolio margin, liquidation, or account-level sizing.",
        "data": meta,
        "candidate_signals_by_symbol_after_filters": candidate_counts,
        "overall": metrics,
        "per_symbol": per_symbol,
        "per_direction": per_direction
    }
    with open(os.path.join(args.out, "frozen_all_filters_holdout.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    fields = [
        "symbol", "variant", "direction", "signal_time_utc", "entry_time_utc",
        "exit_time_utc", "entry", "exit", "exit_reason", "gross_return_pct",
        "fees_and_slippage_pct", "funding_cost_pct", "net_return_pct", "net_R", "bars_held"
    ]
    with open(os.path.join(args.out, "frozen_all_filters_trades.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trades)
    with open(os.path.join(args.out, "frozen_all_filters_summary.md"), "w", encoding="utf-8") as f:
        f.write("# Frozen all_filters independent holdout — research only\n\n")
        f.write(f"- Evaluation window: {TEST_START} to {TEST_END} (end exclusive)\n")
        f.write(f"- Warm-up candles begin: {WARMUP_START}\n")
        f.write(f"- Closed trades: {metrics['closed_trades']}; open at end: {metrics['open_at_end']}\n")
        f.write(f"- Win rate: {metrics['win_rate_pct']:.2f}%\n")
        f.write(f"- Net R: {metrics['closed_net_R']:.3f}; profit factor: {metrics['profit_factor_R']}\n")
        f.write(f"- Approx. max drawdown: {metrics['approx_max_drawdown_pct_at_1pct_risk']:.2f}%\n\n")
        f.write("This run evaluates only the frozen all_filters candidate. No variants were compared and no settings were changed.\n")
    print(json.dumps({"overall": metrics, "per_symbol": per_symbol, "per_direction": per_direction}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
