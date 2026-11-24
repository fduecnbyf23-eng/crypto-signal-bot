#!/usr/bin/env python3
"""Exploratory SHORT-only filter/exit tests with chronological 60d/30d split. Research only."""
import argparse, bisect, csv, json, os, statistics
from collections import defaultdict
from datetime import datetime, timezone

import backtest_strategy as bt

SYMBOLS = bt.SYMBOLS

def load_data(folder):
    data = {}
    first_ts = None
    last_ts = None
    meta = {}
    for symbol in SYMBOLS:
        base = symbol.replace("-", "_")
        bars = bt.read_csv(os.path.join(folder, base + "_SWAP_15m.csv"))
        h1 = bt.read_csv(os.path.join(folder, base + "_SWAP_1H.csv"))
        h4 = bt.read_csv(os.path.join(folder, base + "_SWAP_4H.csv"))
        c1, e1 = bt.higher_lookup(h1, 3600000)
        c4, e4 = bt.higher_lookup(h4, 14400000)
        adx = bt.adx_series(bars)
        atr_hist = []
        signals = {}
        for i in range(99, len(bars) - 1):
            ind = bt.indicators(bars, i)
            if not ind:
                continue
            sig = bt.make_signal(bars, i, ind, adx, h1, h4, e1, e4, c1, c4, atr_hist)
            atr_hist.append(ind["atr_pct"])
            if sig:
                sig["rsi"] = ind["rsi"]
                sig["adx_value"] = adx[i]
                signals[bars[i]["ts"]] = sig
        funding = bt.load_funding(folder, symbol)
        data[symbol] = {
            "bars": bars,
            "bar_map": {b["ts"]: b for b in bars},
            "next_bar": {bars[i]["ts"]: bars[i+1] for i in range(len(bars)-1)},
            "signals": signals,
            "funding": funding,
            "funding_times": [r[0] for r in funding],
        }
        first_ts = min(first_ts or bars[0]["ts"], bars[0]["ts"])
        last_ts = max(last_ts or bars[-1]["ts"], bars[-1]["ts"])
        meta[symbol] = {"candles": len(bars), "signal_candidates": len(signals), "funding_records": len(funding)}
    return data, meta, first_ts, last_ts

def replay(data, cfg, start_ts, end_ts):
    timeline = sorted({ts for x in data.values() for ts in x["bar_map"] if start_ts <= ts < end_ts})
    positions, trades, daily = {}, [], defaultdict(int)
    for ts in timeline:
        exited = set()
        for symbol in SYMBOLS:
            x = data[symbol]
            b = x["bar_map"].get(ts)
            p = positions.get(symbol)
            if b is None or p is None or ts < p["entry_ts"]:
                continue
            hi = bisect.bisect_right(x["funding_times"], ts)
            if hi > p["funding_cursor"]:
                p["funding_sum"] += sum(r for _, r in x["funding"][p["funding_cursor"]:hi])
                p["funding_cursor"] = hi
            sl = b["l"] <= p["stop"] if p["dir"] == "LONG" else b["h"] >= p["stop"]
            tp = b["h"] >= p["target"] if p["dir"] == "LONG" else b["l"] <= p["target"]
            if sl or tp:
                exitp = (min(b["o"], p["stop"]) if p["dir"] == "LONG" else max(b["o"], p["stop"])) if sl else p["target"]
                d = 1 if p["dir"] == "LONG" else -1
                gross = d * (exitp - p["entry"]) / p["entry"]
                costs = 2 * (bt.FEE_SIDE + bt.SLIPPAGE_SIDE)
                funding_cost = d * p["funding_sum"]
                net = gross - costs - funding_cost
                risk = p["risk"] / p["entry"]
                trades.append({"symbol": symbol, "direction": p["dir"], "net_R": net/risk if risk else 0,
                               "exit_reason": "STOP" if sl else "TARGET", "exit_time_ms": ts})
                del positions[symbol]
                exited.add(symbol)
        day = datetime.fromtimestamp((ts + 900000) / 1000, timezone.utc).date().isoformat()
        for symbol in SYMBOLS:
            x = data[symbol]
            if symbol in positions or symbol in exited:
                continue
            sig = x["signals"].get(ts)
            if not sig or sig["direction"] != "SHORT":
                continue
            if not all(sig[k] for k in ("mtf", "adx", "volume", "sr", "volatility")):
                continue
            if sig["adx_value"] is None or sig["adx_value"] < cfg["adx_min"]:
                continue
            if sig["rsi"] > cfg["rsi_max"]:
                continue
            if daily[day] >= 15:
                continue
            nxt = x["next_bar"].get(ts)
            if nxt is None:
                continue
            risk = sig["atr"] * cfg["stop_atr"]
            entry = nxt["o"]
            if risk <= 0 or entry <= 0:
                continue
            cursor = bisect.bisect_right(x["funding_times"], nxt["ts"])
            positions[symbol] = {"dir": "SHORT", "entry_ts": nxt["ts"], "entry": entry,
                                 "stop": entry + risk, "target": entry - cfg["rr"]*risk,
                                 "risk": risk, "funding_sum": 0.0, "funding_cursor": cursor}
            daily[day] += 1
    for symbol, p in positions.items():
        x = data[symbol]
        b = x["bars"][-1]
        hi = bisect.bisect_right(x["funding_times"], b["ts"])
        if hi > p["funding_cursor"]:
            p["funding_sum"] += sum(r for _, r in x["funding"][p["funding_cursor"]:hi])
        gross = -(b["c"] - p["entry"]) / p["entry"]
        costs = 2 * (bt.FEE_SIDE + bt.SLIPPAGE_SIDE)
        net = gross - costs + p["funding_sum"]
        risk = p["risk"] / p["entry"]
        trades.append({"symbol": symbol, "direction": "SHORT", "net_R": net/risk if risk else 0,
                       "exit_reason": "OPEN_AT_END_MARK_TO_CLOSE", "exit_time_ms": b["ts"]})
    closed = [t for t in trades if t["exit_reason"] != "OPEN_AT_END_MARK_TO_CLOSE"]
    wins = [t for t in closed if t["net_R"] > 0]
    losses = [t for t in closed if t["net_R"] < 0]
    gp = sum(t["net_R"] for t in wins)
    gl = -sum(t["net_R"] for t in losses)
    return {"entries_including_open": len(trades), "closed": len(closed), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": 100*len(wins)/len(closed) if closed else 0,
            "net_R": sum(t["net_R"] for t in closed), "profit_factor": gp/gl if gl else None,
            "stops": sum(t["exit_reason"] == "STOP" for t in closed),
            "targets": sum(t["exit_reason"] == "TARGET" for t in closed)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research-data")
    ap.add_argument("--out", default="research-results")
    a = ap.parse_args()
    data, meta, first_ts, last_ts = load_data(a.data)
    split_ts = first_ts + 60*24*60*60*1000
    configs = []
    for adx_min in (18, 22, 25):
        for rsi_max in (50, 45):
            for stop_atr in (1.5, 2.0):
                for rr in (2.0, 2.5, 3.0):
                    configs.append({"adx_min": adx_min, "rsi_max": rsi_max, "stop_atr": stop_atr, "rr": rr})
    results = []
    for cfg in configs:
        train = replay(data, cfg, first_ts, split_ts)
        results.append({**cfg, "train": train})
    results.sort(key=lambda x: (x["train"]["net_R"], x["train"]["profit_factor"] or 0), reverse=True)
    baseline = {"adx_min": 18, "rsi_max": 50, "stop_atr": 1.5, "rr": 2.0}
    chosen = results[:3]
    validation = [{"config": baseline, "validation": replay(data, baseline, split_ts, last_ts + 1)},
                  *[{"config": {k:v for k,v in x.items() if k not in ("train",)}, "validation": replay(data, x, split_ts, last_ts + 1)} for x in chosen]]
    report = {"method": "SHORT-only; all five original filters required; next 15m open entry; max one open per symbol; max 15 entries per UTC day; conservative stop-first; first 60 days exploratory, final 30 days chronological validation; no parameter selection using validation period.",
              "assumptions": "same placeholder 0.05% fee and 0.02% slippage per side as main replay; historical funding applied; not actual fills",
              "split_utc": datetime.fromtimestamp(split_ts/1000, timezone.utc).isoformat(),
              "data": meta, "top_10_train_only": results[:10], "validation": validation}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "short_experiments.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "short_experiments.md"), "w", encoding="utf-8") as f:
        f.write("# SHORT-only exploratory experiments\n\nResearch only. First 60 days used for exploration; last 30 days held out chronologically.\n\n")
        f.write("| Config | Train net R | Train PF | Validation net R | Validation PF | Validation trades |\n|---|---:|---:|---:|---:|---:|\n")
        val = validation
        for item in val:
            c=item["config"]; v=item["validation"]
            tr = next((x["train"] for x in results if all(x[k]==c[k] for k in c)), None)
            trnet = tr["net_R"] if tr else "baseline"
            trpf = tr["profit_factor"] if tr else ""
            f.write(f'| ADX≥{c["adx_min"]}, RSI≤{c["rsi_max"]}, SL {c["stop_atr"]} ATR, TP {c["rr"]}R | {trnet} | {trpf} | {v["net_R"]:.2f} | {v["profit_factor"]} | {v["closed"]} |\n')
        f.write("\nDo not promote any setting to live trading from this small sample. Require more data and another untouched validation period.\n")
    print(json.dumps({"split_utc": report["split_utc"], "top_10_train_only": results[:10], "validation": validation}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
