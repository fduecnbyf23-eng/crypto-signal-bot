#!/usr/bin/env python3
"""Frozen indicator backtest. Research only; never places orders."""
import argparse
import csv
import os
from collections import defaultdict
from datetime import datetime, timezone

from indicator_features import build_features, apply_timeframe_scope

TF_MS = {"15m": 900_000, "1H": 3_600_000, "4H": 14_400_000, "1Dutc": 86_400_000}
FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
FUNDING_INTERVAL_MS = 8 * 60 * 60 * 1000
HOLDOUT_1Y = int(datetime(2026, 7, 26, tzinfo=timezone.utc).timestamp() * 1000)
HOLDOUT_2Y_DAILY = int(datetime(2026, 5, 25, tzinfo=timezone.utc).timestamp() * 1000)

STRATEGIES = {
    "ema20_bounce": ("1H", "4H", "1Dutc", "ema20_bounce_long", "ema20_bounce_short"),
    "rsi_extreme": ("15m", "1H", "4H", "rsi_cross_up_30", "rsi_cross_down_70"),
    "rsi_divergence": ("15m", "1H", "4H", "rsi_bullish_divergence", "rsi_bearish_divergence"),
    "vpvr_value_area": ("1H", "4H", "vpvr_bounce_long", "vpvr_bounce_short"),
    "bb_squeeze_breakout": ("1H", "4H", "bb_breakout_up", "bb_breakout_down"),
    "macd_cross": ("4H", "1Dutc", "macd_cross_up", "macd_cross_down"),
    "vwap_bounce": ("15m", "1H", "vwap_bounce_long", "vwap_bounce_short"),
    "ema_macd": ("4H", "1Dutc", "ema_macd_long", "ema_macd_short"),
    "rsi_volume": ("15m", "1H", "4H", "rsi_volume_long", "rsi_volume_short"),
    "vwap_ema": ("1H", "vwap_ema_long", "vwap_ema_short"),
}
RSI_EXIT_STRATEGIES = {"rsi_extreme", "rsi_divergence", "rsi_volume"}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def funding_map(path):
    if not os.path.exists(path):
        return {}, None, None, False
    rows = read_csv(path)
    items = {int(r["funding_time_ms"]): float(r["rate"]) for r in rows}
    if not items:
        return {}, None, None, False
    stamps = sorted(items)
    contiguous = all(b - a == FUNDING_INTERVAL_MS for a, b in zip(stamps, stamps[1:]))
    return items, stamps[0], stamps[-1], contiguous


def funding_r_for_interval(fmap, first_ts, direction, entry_price, risk_dist, entry_ts, exit_ts):
    if first_ts is None or entry_ts < first_ts:
        return 0.0, False
    total = 0.0
    expected = range(first_ts, exit_ts + 1, FUNDING_INTERVAL_MS)
    for ts in expected:
        if ts <= entry_ts:
            continue
        rate = fmap.get(ts)
        if rate is None:
            return 0.0, False
        # Constant entry notional is used because OHLCV does not provide mark price at each funding instant.
        total += -direction * rate * entry_price / risk_dist
    return total, True


def adverse_exit_price(direction, raw_price, fee_rate=FEE_PER_SIDE, slip_rate=SLIPPAGE_PER_SIDE):
    # Costs are deducted separately in R; keep raw exchange trigger price here.
    return raw_price


def simulate(rows, features, tf, long_flag, short_flag, market, symbol, strategy,
             exit_mode, period, entry_start, entry_end, fmap, funding_first, funding_contiguous):
    interval = TF_MS[tf]
    trades = []
    position = None
    invalid_funding = 0
    last_index = len(rows) - 1
    if entry_end is not None:
        eligible = [i for i, r in enumerate(rows) if int(r["timestamp_ms"]) < entry_end]
        if not eligible:
            return trades, invalid_funding
        last_index = eligible[-1]
    end_ts = int(rows[last_index]["timestamp_ms"]) + interval

    def finish(pos, exit_idx, exit_ts, raw_exit, reason, closed=True):
        nonlocal invalid_funding
        direction = pos["direction"]
        gross = direction * (raw_exit - pos["entry_price"]) / pos["risk_dist"]
        exit_cost_factor = raw_exit / pos["risk_dist"]
        entry_cost_factor = pos["entry_price"] / pos["risk_dist"]
        base_cost = (FEE_PER_SIDE + SLIPPAGE_PER_SIDE) * (entry_cost_factor + exit_cost_factor)
        funding_r, funding_ok = (0.0, True)
        if market == "SWAP":
            funding_r, funding_ok = funding_r_for_interval(
                fmap, funding_first, direction, pos["entry_price"], pos["risk_dist"],
                pos["entry_ts"], exit_ts
            )
            if not funding_ok or not funding_contiguous:
                invalid_funding += 1
        net = gross - base_cost + funding_r
        net_010 = gross - 0.0005 * (entry_cost_factor + exit_cost_factor) + funding_r
        net_020 = gross - 0.0010 * (entry_cost_factor + exit_cost_factor) + funding_r
        trades.append({
            "market": market, "symbol": symbol, "timeframe": tf, "strategy": strategy,
            "exit_mode": exit_mode, "period": period,
            "direction": "LONG" if direction == 1 else "SHORT",
            "signal_time_utc": datetime.fromtimestamp(pos["signal_ts"]/1000, timezone.utc).isoformat(),
            "entry_time_utc": datetime.fromtimestamp(pos["entry_ts"]/1000, timezone.utc).isoformat(),
            "exit_time_utc": datetime.fromtimestamp(exit_ts/1000, timezone.utc).isoformat(),
            "entry_price": round(pos["entry_price"], 10), "exit_price": round(raw_exit, 10),
            "stop_price": round(pos["stop"], 10), "target_price": "" if pos["target"] is None else round(pos["target"], 10),
            "risk_distance": round(pos["risk_dist"], 10), "bars_held": exit_idx-pos["entry_idx"]+1,
            "exit_reason": reason, "gross_R": round(gross, 6), "cost_R": round(base_cost, 6),
            "funding_R": round(funding_r, 6), "net_R": round(net, 6),
            "net_R_at_0_10pct_roundtrip": round(net_010, 6),
            "net_R_at_0_20pct_roundtrip": round(net_020, 6),
            "funding_valid": funding_ok if market == "SWAP" else True,
            "closed": closed
        })

    for i in range(len(rows)):
        row = rows[i]
        ts = int(row["timestamp_ms"])
        op, hi, lo = float(row["open"]), float(row["high"]), float(row["low"])
        cl = float(row["close"])
        feat = features[i]

        if position is not None:
            pos = position
            d = pos["direction"]
            # Stop gap has priority over all other exits.
            if (d == 1 and op <= pos["stop"]) or (d == -1 and op >= pos["stop"]):
                finish(pos, i, ts, op, "STOP_GAP")
                position = None
                continue
            if pos["pending_rsi_exit"]:
                finish(pos, i, ts, op, "RSI_EXTREME_NEXT_OPEN")
                position = None
                continue
            if pos["target"] is not None and ((d == 1 and op >= pos["target"]) or (d == -1 and op <= pos["target"])):
                finish(pos, i, ts, pos["target"], "TARGET_GAP")
                position = None
                continue

            hit_stop = (lo <= pos["stop"]) if d == 1 else (hi >= pos["stop"])
            hit_target = False if pos["target"] is None else ((hi >= pos["target"]) if d == 1 else (lo <= pos["target"]))
            if hit_stop:
                finish(pos, i, ts, pos["stop"], "STOP")
                position = None
                continue
            if hit_target:
                finish(pos, i, ts, pos["target"], "TARGET")
                position = None
                continue

            if exit_mode == "rsi_extreme":
                rsi = feat.get("rsi14")
                if rsi is not None and ((d == 1 and float(rsi) >= 70) or (d == -1 and float(rsi) <= 30)):
                    pos["pending_rsi_exit"] = True

        if position is None and i < last_index:
            next_ts = int(rows[i+1]["timestamp_ms"])
            # Entry only at the next candle open, and only across a contiguous candle boundary.
            if next_ts != ts + interval:
                continue
            if entry_start is not None and next_ts < entry_start:
                continue
            if entry_end is not None and next_ts >= entry_end:
                continue
            atr = feat.get("atr14")
            if atr is None or float(atr) <= 0:
                continue
            direction = 1 if bool(feat.get(long_flag)) else (-1 if bool(feat.get(short_flag)) else 0)
            if market == "SPOT" and direction < 0:
                direction = 0
            if direction == 0:
                continue
            entry_price = float(rows[i+1]["open"])
            risk_dist = 1.5 * float(atr)
            if entry_price <= 0 or risk_dist <= 0:
                continue
            stop = entry_price - direction * risk_dist
            target = None if exit_mode == "rsi_extreme" else entry_price + direction * 2.0 * risk_dist
            position = {
                "direction": direction, "signal_ts": ts, "entry_ts": next_ts,
                "entry_idx": i+1, "entry_price": entry_price, "risk_dist": risk_dist,
                "stop": stop, "target": target, "pending_rsi_exit": False
            }

    if position is not None:
        # Mark-to-market open position at final closed candle; not counted as a closed trade.
        pos = position
        last_close = float(rows[last_index]["close"])
        d = pos["direction"]
        gross = d * (last_close - pos["entry_price"]) / pos["risk_dist"]
        entry_factor = pos["entry_price"] / pos["risk_dist"]
        exit_factor = last_close / pos["risk_dist"]
        cost = (FEE_PER_SIDE + SLIPPAGE_PER_SIDE) * (entry_factor + exit_factor)
        funding_r, funding_ok = (0.0, True)
        if market == "SWAP":
            funding_r, funding_ok = funding_r_for_interval(
                fmap, funding_first, d, pos["entry_price"], pos["risk_dist"],
                pos["entry_ts"], end_ts
            )
            if not funding_ok or not funding_contiguous:
                invalid_funding += 1
        trades.append({
            "market": market, "symbol": symbol, "timeframe": tf, "strategy": strategy,
            "exit_mode": exit_mode, "period": period,
            "direction": "LONG" if d == 1 else "SHORT",
            "signal_time_utc": datetime.fromtimestamp(pos["signal_ts"]/1000, timezone.utc).isoformat(),
            "entry_time_utc": datetime.fromtimestamp(pos["entry_ts"]/1000, timezone.utc).isoformat(),
            "exit_time_utc": "", "entry_price": round(pos["entry_price"], 10),
            "exit_price": "", "stop_price": round(pos["stop"], 10),
            "target_price": "" if pos["target"] is None else round(pos["target"], 10),
            "risk_distance": round(pos["risk_dist"], 10), "bars_held": last_index-pos["entry_idx"]+1,
            "exit_reason": "OPEN_AT_DATA_END", "gross_R": round(gross, 6),
            "cost_R": round(cost, 6), "funding_R": round(funding_r, 6),
            "net_R": round(gross-cost+funding_r, 6),
            "net_R_at_0_10pct_roundtrip": round(gross-0.0005*(entry_factor+exit_factor)+funding_r, 6),
            "net_R_at_0_20pct_roundtrip": round(gross-0.0010*(entry_factor+exit_factor)+funding_r, 6),
            "funding_valid": funding_ok if market == "SWAP" else True, "closed": False
        })
    return trades, invalid_funding


def summarize(trades, invalid_funding):
    closed = [t for t in trades if t["closed"]]
    opens = [t for t in trades if not t["closed"]]
    wins = [float(t["net_R"]) for t in closed if float(t["net_R"]) > 0]
    losses = [float(t["net_R"]) for t in closed if float(t["net_R"]) < 0]
    total = sum(float(t["net_R"]) for t in closed)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in closed:
        equity += float(t["net_R"])
        peak = max(peak, equity)
        max_dd = max(max_dd, peak-equity)
    symbols = sorted({t["symbol"] for t in closed})
    per_symbol = {s: sum(1 for t in closed if t["symbol"] == s) for s in symbols}
    valid_funding = invalid_funding == 0
    return {
        "trades_closed": len(closed), "open_at_end": len(opens),
        "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(100*len(wins)/len(closed), 3) if closed else "",
        "net_R": round(total, 6) if valid_funding else "",
        "expectancy_R": round(total/len(closed), 6) if closed and valid_funding else "",
        "profit_factor": (round(gross_profit/gross_loss, 6) if gross_loss else ("INF" if gross_profit else "")) if valid_funding else "",
        "max_drawdown_R": round(max_dd, 6) if valid_funding else "",
        "net_R_cost_0_10pct_roundtrip": round(sum(float(t["net_R_at_0_10pct_roundtrip"]) for t in closed), 6) if valid_funding else "",
        "net_R_cost_0_20pct_roundtrip": round(sum(float(t["net_R_at_0_20pct_roundtrip"]) for t in closed), 6) if valid_funding else "",
        "invalid_funding_trades": invalid_funding,
        "funding_valid": valid_funding,
        "symbol_closed_counts": ";".join(f"{k}:{v}" for k,v in per_symbol.items())
    }


def main():
    p = argparse.ArgumentParser(description="Frozen indicator backtest; no live orders.")
    p.add_argument("--input-1y", default="research-data")
    p.add_argument("--input-2y-daily", default="research-daily-2y")
    p.add_argument("--output-dir", default="frozen-indicator-backtest")
    args = p.parse_args()
    all_trades, summaries = [], []
    symbols = ["BTC", "ETH", "SOL", "BNB", "XRP"]
    for symbol in symbols:
        for market, suffix in (("SPOT", ""), ("SWAP", "_SWAP")):
            funding_path = os.path.join(args.input_1y, f"{symbol}_USDT_SWAP_funding.csv")
            fmap, funding_first, funding_last, funding_contiguous = funding_map(funding_path) if market == "SWAP" else ({}, None, None, True)
            for tf in ("15m", "1H", "4H"):
                src = os.path.join(args.input_1y, f"{symbol}_USDT{suffix}_{tf}.csv")
                if not os.path.exists(src):
                    raise FileNotFoundError(src)
                rows = read_csv(src)
                features = apply_timeframe_scope(build_features(rows), tf)
                for strategy, spec in STRATEGIES.items():
                    allowed = spec[:-2] if strategy != "vwap_ema" else (spec[0],)
                    if tf not in allowed:
                        continue
                    long_flag, short_flag = spec[-2], spec[-1]
                    modes = ("base", "rsi_extreme") if strategy in RSI_EXIT_STRATEGIES else ("base",)
                    for exit_mode in modes:
                        for period, start, end in (("development", None, HOLDOUT_1Y), ("holdout", HOLDOUT_1Y, None)):
                            trades, invalid = simulate(
                                rows, features, tf, long_flag, short_flag, market, symbol,
                                strategy, exit_mode, period, start, end, fmap, funding_first, funding_contiguous
                            )
                            all_trades.extend(trades)
                            summary = summarize(trades, invalid)
                            summaries.append({
                                "market": market, "symbol": symbol, "timeframe": tf,
                                "strategy": strategy, "exit_mode": exit_mode, "period": period,
                                "holdout_start_utc": "2026-07-26T00:00:00+00:00",
                                **summary
                            })
            # Daily strategies use the separate two-year daily archive.
            tf = "1Dutc"
            src = os.path.join(args.input_2y_daily, f"{symbol}_USDT{suffix}_{tf}.csv")
            if not os.path.exists(src):
                raise FileNotFoundError(src)
            rows = read_csv(src)
            features = apply_timeframe_scope(build_features(rows), tf)
            for strategy, spec in STRATEGIES.items():
                allowed = spec[:-2] if strategy != "vwap_ema" else (spec[0],)
                if tf not in allowed:
                    continue
                long_flag, short_flag = spec[-2], spec[-1]
                dev_start = funding_first if market == "SWAP" else None
                for period, start, end in (("development", dev_start, HOLDOUT_2Y_DAILY), ("holdout", HOLDOUT_2Y_DAILY, None)):
                    trades, invalid = simulate(
                        rows, features, tf, long_flag, short_flag, market, symbol,
                        strategy, "base", period, start, end, fmap, funding_first, funding_contiguous
                    )
                    all_trades.extend(trades)
                    summaries.append({
                        "market": market, "symbol": symbol, "timeframe": tf,
                        "strategy": strategy, "exit_mode": "base", "period": period,
                        "holdout_start_utc": "2026-05-25T00:00:00+00:00",
                        **summarize(trades, invalid)
                    })
    os.makedirs(args.output_dir, exist_ok=True)
    write_csv(os.path.join(args.output_dir, "trades.csv"), all_trades)
    write_csv(os.path.join(args.output_dir, "summary.csv"), summaries)
    print(f"BACKTEST_COMPLETE trades_including_open={len(all_trades)} summary_rows={len(summaries)}")
    print("Research only. No orders were generated.")


if __name__ == "__main__":
    main()
