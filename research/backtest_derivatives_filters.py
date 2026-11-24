#!/usr/bin/env python3
"""Compare OKX SWAP strategy with 4H derivatives filters. Research only."""
import argparse, bisect, csv, json, os, statistics
from datetime import datetime, timezone
import backtest_strategy as bt

SYMBOLS = bt.SYMBOLS
FOUR_HOURS_MS = 4 * 60 * 60 * 1000
MAX_METRIC_AGE_MS = 8 * 60 * 60 * 1000
SPECS = {
    "oi": ("open_interest", "oi_usd"),
    "taker": ("taker_volume", None),
    "top_position": ("top_trader_position_ratio", "top_trader_long_short_position_ratio"),
    "top_account": ("top_trader_account_ratio", "top_trader_long_short_account_ratio"),
    "all_account": ("all_trader_account_ratio", "all_trader_long_short_account_ratio"),
}

def read_metric(path, value_key):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = int(r["timestamp_ms"])
            if value_key is None:
                buy, sell = float(r["taker_buy_volume_usd"]), float(r["taker_sell_volume_usd"])
                value = buy / max(sell, 1e-12)
            else:
                value = float(r[value_key])
            if value == value and abs(value) != float("inf"):
                rows.append((ts + FOUR_HOURS_MS, value, ts))
    rows.sort()
    return {"rows": rows, "available": [x[0] for x in rows]}

def load_metrics(folder, symbol):
    base = symbol.replace("-", "_") + "_SWAP_"
    result = {}
    for key, (filename, value_key) in SPECS.items():
        path = os.path.join(folder, base + filename + "_4H.csv")
        if not os.path.isfile(path):
            raise FileNotFoundError("Missing derivatives metric: " + path)
        result[key] = read_metric(path, value_key)
        if not result[key]["rows"]:
            raise RuntimeError("Empty derivatives metric: " + path)
    return result

def get_features(metrics, close_ts, direction):
    idx = {}
    for key, series in metrics.items():
        i = bisect.bisect_right(series["available"], close_ts) - 1
        if i < 0 or close_ts - series["available"][i] > MAX_METRIC_AGE_MS:
            return None
        idx[key] = i
    oi = metrics["oi"]["rows"]
    oi_i = idx["oi"]
    if oi_i < 3:
        return None
    old, current = oi[oi_i - 3], oi[oi_i]
    span = current[2] - old[2]
    if not (10 * 60 * 60 * 1000 <= span <= 16 * 60 * 60 * 1000) or old[1] <= 0:
        return None
    oi_change = current[1] / old[1] - 1.0
    taker = metrics["taker"]["rows"][idx["taker"]][1]
    top_pos = metrics["top_position"]["rows"][idx["top_position"]][1]
    top_acc = metrics["top_account"]["rows"][idx["top_account"]][1]
    all_acc = metrics["all_account"]["rows"][idx["all_account"]][1]
    is_long = direction == "LONG"
    taker_ok = taker >= 1.05 if is_long else taker <= 1 / 1.05
    top_pos_ok = top_pos > 1 if is_long else top_pos < 1
    top_acc_ok = top_acc > 1 if is_long else top_acc < 1
    all_acc_ok = all_acc > 1 if is_long else all_acc < 1
    oi_ok = oi_change > 0.0025
    return {
        "oi_taker": oi_ok and taker_ok, "taker_only": taker_ok, "oi_only": oi_ok,
        "top_position": top_pos_ok, "top_account": top_acc_ok, "all_account": all_acc_ok,
        "combined": oi_ok and taker_ok and top_pos_ok,
    }

def load_data(data_folder, metrics_folder):
    data, meta, starts, ends = {}, {}, [], []
    for symbol in SYMBOLS:
        base = symbol.replace("-", "_")
        bars = bt.read_csv(os.path.join(data_folder, base + "_SWAP_15m.csv"))
        h1 = bt.read_csv(os.path.join(data_folder, base + "_SWAP_1H.csv"))
        h4 = bt.read_csv(os.path.join(data_folder, base + "_SWAP_4H.csv"))
        if not bars or not h1 or not h4:
            raise RuntimeError("Missing or empty SWAP candle data for " + symbol)
        metrics = load_metrics(metrics_folder, symbol)
        for series in metrics.values():
            starts.append(series["available"][0])
            ends.append(series["available"][-1])
        c1, e1 = bt.higher_lookup(h1, 3600000)
        c4, e4 = bt.higher_lookup(h4, 14400000)
        adx, atr_hist, signals = bt.adx_series(bars), [], {}
        joined = 0
        for i in range(99, len(bars) - 1):
            ind = bt.indicators(bars, i)
            if not ind:
                continue
            sig = bt.make_signal(bars, i, ind, adx, h1, h4, e1, e4, c1, c4, atr_hist)
            atr_hist.append(ind["atr_pct"])
            if not sig:
                continue
            features = get_features(metrics, bars[i]["ts"] + 900000, sig["direction"])
            if features is None:
                continue
            sig.update(features)
            signals[bars[i]["ts"]] = sig
            joined += 1
        funding = bt.load_funding(data_folder, symbol)
        data[symbol] = {
            "bars": bars, "bar_map": {b["ts"]: b for b in bars},
            "next_bar": {bars[i]["ts"]: bars[i+1] for i in range(len(bars)-1)},
            "signals": signals, "funding": funding,
            "funding_times": [r[0] for r in funding],
        }
        meta[symbol] = {"swap_15m_bars": len(bars), "funding_records": len(funding),
                        "signals_with_all_metrics": joined}
    start = ((max(starts) + 899999) // 900000) * 900000
    end = (min(ends) // 900000) * 900000
    if end <= start:
        raise RuntimeError("No common overlap between candles and all metrics")
    return data, meta, start, end

def run_window(data, start, end, variant):
    subset = {}
    for symbol, x in data.items():
        bars = [b for b in x["bars"] if start <= b["ts"] < end]
        keys = {b["ts"] for b in bars}
        signals = {k: v for k, v in x["signals"].items() if k in keys}
        if variant != "baseline":
            signals = {k: v for k, v in signals.items() if v.get(variant, False)}
        subset[symbol] = {
            **x, "bars": bars,
            "bar_map": {k: x["bar_map"][k] for k in keys},
            "next_bar": {k: v for k, v in x["next_bar"].items() if k in keys and v["ts"] < end},
            "signals": signals,
        }
    return bt.summarize(bt.simulate(subset, variant))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="research-data")
    p.add_argument("--metrics", default="research-derivatives")
    p.add_argument("--out", default="research-results")
    a = p.parse_args()
    data, meta, start, end = load_data(a.data, a.metrics)
    split = start + int((end - start) * 0.70)
    variants = ["baseline", "oi_taker", "taker_only", "oi_only",
                "top_position", "top_account", "all_account", "combined"]
    results = {}
    for v in variants:
        results[v] = {
            "train": run_window(data, start, split, v),
            "holdout": run_window(data, split, end, v),
        }
    iso = lambda ts: datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()
    report = {
        "market": "OKX USDT perpetual SWAP",
        "method": "Same common period for all variants; first 70% chronological research segment and final 30% untouched holdout. Signal on closed 15m candle, entry next 15m open. Every 4H metric is delayed 4h from its timestamp; stale metrics older than 8h are rejected. No parameter optimization.",
        "costs": "0.05% fee and 0.02% slippage per side, plus historical funding; estimates, not actual fills.",
        "rules": {
            "oi_only": "OI USD rises more than 0.25% over three 4H observations (about 12h).",
            "taker_only": "Taker buy/sell >= 1.05 for LONG, <= 1/1.05 for SHORT.",
            "top_position": "Top trader position ratio > 1 for LONG, < 1 for SHORT.",
            "top_account": "Top trader account ratio > 1 for LONG, < 1 for SHORT.",
            "all_account": "All trader account ratio > 1 for LONG, < 1 for SHORT.",
            "oi_taker": "Rising OI plus taker flow aligned with trade direction.",
            "combined": "Rising OI plus aligned taker flow and top-trader position ratio.",
        },
        "common_start_utc": iso(start), "common_end_utc": iso(end),
        "holdout_start_utc": iso(split), "data": meta, "results": results,
    }
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "derivatives_filter_comparison.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "derivatives_filter_comparison.md"), "w", encoding="utf-8") as f:
        f.write("# OKX derivatives metrics comparison (research only)\n\n")
        f.write(f"Common period: {iso(start)} to {iso(end)} UTC. Holdout begins {iso(split)}.\n\n")
        f.write("All variants use identical dates, SWAP candles, costs and funding. 4H metrics are delayed 4h and stale values older than 8h are rejected.\n\n")
        f.write("| Variant | Segment | Closed trades | Win rate | Net R | Profit factor | Approx. DD |\n|---|---|---:|---:|---:|---:|---:|\n")
        for v in variants:
            for segment in ("train", "holdout"):
                m = results[v][segment]
                pf = m["profit_factor_R"]
                f.write(f"| {v} | {segment} | {m['closed_trades']} | {m['win_rate_pct']:.1f}% | {m['closed_net_R']:.2f} | {pf if pf is not None else 'n/a'} | {m['approx_max_drawdown_pct_at_1pct_risk']:.1f}% |\n")
        f.write("\nA filter is interesting only if it improves the untouched holdout against the same-period baseline and remains robust to higher costs. Do not promote a negative-PF strategy to live trading.\n")
    print(json.dumps({"common_start_utc": iso(start), "common_end_utc": iso(end),
                      "holdout_start_utc": iso(split), "results": results}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
