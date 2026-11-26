#!/usr/bin/env python3
"""Predeclared filter study for EMA50 + RSI + volume on OKX USDT-SWAP. Research only."""
import argparse, bisect, csv, json, os, statistics
from datetime import datetime, timezone
import backtest_strategy as bt

SYMBOLS = bt.SYMBOLS
# Fixed before inspecting this study's holdout results; no parameter sweep.
FILTERS = {
    "mtf": "15m signal direction agrees with the last fully closed 1H and 4H EMA50",
    "adx": "ADX(14) >= 18 on the 15m chart",
    "sr_room": "at least 0.5 ATR room to the prior 20-bar high (LONG) or low (SHORT)",
    "atr_regime": "current ATR/price is 0.5x to 2.0x the median of the prior 96 15m bars",
}
VARIANTS = {
    "baseline": [],
    "mtf": ["mtf"],
    "adx": ["adx"],
    "sr_room": ["sr_room"],
    "atr_regime": ["atr_regime"],
    "mtf_adx": ["mtf", "adx"],
    "mtf_sr_room": ["mtf", "sr_room"],
    "adx_sr_room": ["adx", "sr_room"],
    "mtf_adx_sr_room": ["mtf", "adx", "sr_room"],
    "all_filters": ["mtf", "adx", "sr_room", "atr_regime"],
}

def rsi14(closes, i):
    changes = [closes[k] - closes[k-1] for k in range(i-13, i+1)]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains) / 14.0
    avg_loss = sum(losses) / 14.0
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

def build_signals(bars, h1, h4):
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    ema50 = bt.ema(closes, 50)
    adx = bt.adx_series(bars, 14)
    h1_close_times = [b["ts"] + 3600000 for b in h1]
    h4_close_times = [b["ts"] + 14400000 for b in h4]
    h1_ema = bt.ema([b["c"] for b in h1], 50)
    h4_ema = bt.ema([b["c"] for b in h4], 50)
    atr_pct_history = []
    signals = {}

    for i in range(99, len(bars)-1):
        ind = bt.indicators(bars, i)
        if not ind:
            continue
        price = closes[i]
        prev_volumes = volumes[i-20:i]
        volume_ok = len(prev_volumes) == 20 and volumes[i] > statistics.mean(prev_volumes) * 1.2
        strength = rsi14(closes, i)
        direction = None
        if price > ema50[i] and 52.0 < strength < 68.0 and volume_ok:
            direction = "LONG"
        elif price < ema50[i] and 32.0 < strength < 48.0 and volume_ok:
            direction = "SHORT"

        prior_atr = atr_pct_history[-96:]
        atr_median = statistics.median(prior_atr) if len(prior_atr) == 96 else None
        atr_regime_ok = (
            atr_median is not None and atr_median > 0
            and 0.5 * atr_median <= ind["atr_pct"] <= 2.0 * atr_median
        )

        # Every filter uses information available no later than the signal candle close.
        signal_close_ts = bars[i]["ts"] + 900000
        j1 = bisect.bisect_right(h1_close_times, signal_close_ts) - 1
        j4 = bisect.bisect_right(h4_close_times, signal_close_ts) - 1
        if direction and j1 >= 49 and j4 >= 49:
            mtf_ok = (
                h1[j1]["c"] > h1_ema[j1] and h4[j4]["c"] > h4_ema[j4]
                if direction == "LONG" else
                h1[j1]["c"] < h1_ema[j1] and h4[j4]["c"] < h4_ema[j4]
            )
        else:
            mtf_ok = False

        adx_ok = adx[i] is not None and adx[i] >= 18.0
        prior_bars = bars[i-20:i]
        if len(prior_bars) == 20:
            prior_high = max(b["h"] for b in prior_bars)
            prior_low = min(b["l"] for b in prior_bars)
            sr_room_ok = (
                prior_high - price >= 0.5 * ind["atr"]
                if direction == "LONG" else
                price - prior_low >= 0.5 * ind["atr"]
            ) if direction else False
        else:
            sr_room_ok = False

        if direction:
            signals[bars[i]["ts"]] = {
                "direction": direction,
                "atr": ind["atr"],
                "mtf": mtf_ok,
                "adx": adx_ok,
                "sr_room": sr_room_ok,
                "atr_regime": atr_regime_ok,
            }
        atr_pct_history.append(ind["atr_pct"])
    return signals

def build_data(folder):
    data = {}
    meta = {}
    for symbol in SYMBOLS:
        base = symbol.replace("-", "_") + "_SWAP"
        paths = {
            "15m": os.path.join(folder, base + "_15m.csv"),
            "1H": os.path.join(folder, base + "_1H.csv"),
            "4H": os.path.join(folder, base + "_4H.csv"),
        }
        missing = [p for p in paths.values() if not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError("Missing required SWAP candle files: " + ", ".join(missing))
        bars, h1, h4 = (bt.read_csv(paths[k]) for k in ("15m", "1H", "4H"))
        if min(len(bars), len(h1), len(h4)) < 100:
            raise RuntimeError(f"Insufficient SWAP history for {symbol}")
        funding = bt.load_funding(folder, symbol)
        data[symbol] = {
            "bars": bars,
            "bar_map": {b["ts"]: b for b in bars},
            "next_bar": {bars[i]["ts"]: bars[i+1] for i in range(len(bars)-1)},
            "signals": build_signals(bars, h1, h4),
            "funding": funding,
            "funding_times": [x[0] for x in funding],
        }
        meta[symbol] = {
            "15m_bars": len(bars), "1h_bars": len(h1), "4h_bars": len(h4),
            "baseline_candidates": len(data[symbol]["signals"]),
            "funding_records": len(funding),
        }
        print(f'{symbol}: {len(bars)} 15m bars, {len(data[symbol]["signals"])} EMA/RSI/volume candidates, {len(funding)} funding records', flush=True)
    return data, meta

def window_data(data, start, end, required_filters):
    subset = {}
    candidate_counts = {}
    for symbol, x in data.items():
        bars = [b for b in x["bars"] if start <= b["ts"] < end]
        keys = {b["ts"] for b in bars}
        sigs = {
            ts: sig for ts, sig in x["signals"].items()
            if ts in keys and all(sig.get(k, False) for k in required_filters)
        }
        candidate_counts[symbol] = len(sigs)
        subset[symbol] = {
            **x,
            "bars": bars,
            "bar_map": {k: x["bar_map"][k] for k in keys},
            "next_bar": {k: v for k, v in x["next_bar"].items() if k in keys and v["ts"] < end},
            "signals": sigs,
        }
    return subset, candidate_counts

def run_variant(data, start, end, filters):
    subset, counts = window_data(data, start, end, filters)
    trades = bt.simulate(subset, "baseline")
    for trade in trades:
        trade["variant"] = "baseline" if not filters else "+".join(filters)
    return bt.summarize(trades), trades, counts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research-data")
    ap.add_argument("--out", default="research-results")
    args = ap.parse_args()

    allbars = {
        s: bt.read_csv(os.path.join(args.data, s.replace("-", "_") + "_SWAP_15m.csv"))
        for s in SYMBOLS
    }
    if any(len(v) < 500 for v in allbars.values()):
        raise RuntimeError("Insufficient 15m SWAP candles for common test period")
    start = max(v[0]["ts"] for v in allbars.values())
    end = min(v[-1]["ts"] for v in allbars.values())
    if end <= start:
        raise RuntimeError("No common candle overlap across all five SWAP instruments")
    split = start + int((end-start) * 0.70)

    data, meta = build_data(args.data)
    results = {}
    all_trades = []
    for name, filters in VARIANTS.items():
        results[name] = {}
        for segment, seg_start, seg_end in (
            ("train", start, split), ("holdout", split, end)
        ):
            metrics, trades, counts = run_variant(data, seg_start, seg_end, filters)
            results[name][segment] = {
                **metrics,
                "candidate_signals_by_symbol": counts,
                "filters": filters,
            }
            all_trades.extend(trades)
        print(f'{name}: train PF={results[name]["train"]["profit_factor_R"]}, holdout PF={results[name]["holdout"]["profit_factor_R"]}', flush=True)

    os.makedirs(args.out, exist_ok=True)
    fields = [
        "symbol", "variant", "direction", "signal_time_utc", "entry_time_utc",
        "exit_time_utc", "entry", "exit", "exit_reason", "gross_return_pct",
        "fees_and_slippage_pct", "funding_cost_pct", "net_return_pct", "net_R", "bars_held"
    ]
    with open(os.path.join(args.out, "ema_filter_study_trades.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_trades)

    iso = lambda x: datetime.fromtimestamp(x/1000, timezone.utc).isoformat()
    report = {
        "market": "OKX USDT perpetual SWAP",
        "common_start_utc": iso(start), "common_end_utc": iso(end),
        "holdout_start_utc": iso(split),
        "method": "Same EMA50 + arithmetic-average RSI14 + volume > 1.2x prior-20 mean baseline; closed 15m signal, next 15m open entry; chronological 70/30 split; one open position per symbol; 15 new entries per UTC day; ATR stop 1.5x and target 2R; stop assumed first on same-candle SL/TP.",
        "filters": FILTERS,
        "variants": VARIANTS,
        "costs": "Estimated 0.05% fee and 0.02% slippage per side plus historical OKX funding where available. Actual fills/rates may differ.",
        "no_tuning": "Thresholds and combinations were fixed in source before this run. No parameter optimization was performed. Comparing many variants still creates multiple-comparison risk; holdout results are exploratory, not proof.",
        "data": meta,
        "results": results,
    }
    with open(os.path.join(args.out, "ema_filter_study.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(os.path.join(args.out, "ema_filter_study_summary.md"), "w", encoding="utf-8") as f:
        f.write("# EMA + RSI + volume: predeclared filter study (research only)\n\n")
        f.write(f"Common candles: {iso(start)} to {iso(end)} UTC. Holdout starts {iso(split)}.\n\n")
        f.write("All variants share the same baseline entries, exits, risk, daily cap, costs and funding assumptions. Filters are causal and fixed; no threshold tuning.\n\n")
        f.write("| Variant | Segment | Closed trades | Win rate | Net R | Avg R | PF | Approx DD* |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
        for name in VARIANTS:
            for segment in ("train", "holdout"):
                m = results[name][segment]
                pf = "n/a" if m["profit_factor_R"] is None else f'{m["profit_factor_R"]:.3f}'
                f.write(f'| {name} | {segment} | {m["closed_trades"]} | {m["win_rate_pct"]:.1f}% | {m["closed_net_R"]:.2f} | {m["average_closed_net_R"]:.3f} | {pf} | {m["approx_max_drawdown_pct_at_1pct_risk"]:.1f}% |\n')
        f.write("\n*Approximate compounded-R drawdown; overlapping positions, correlation and portfolio margin are not modeled. Simulation only. PF below 1 is unprofitable.\n")
        f.write("\nImportant: testing multiple filters on one holdout increases selection bias. Any promising result must be frozen and tested on a later untouched period or in paper trading.\n")
    print(json.dumps({"holdout": {k: results[k]["holdout"] for k in VARIANTS}}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
