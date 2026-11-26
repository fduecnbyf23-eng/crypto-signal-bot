#!/usr/bin/env python3
"""Frozen AI-designed 4H trend-pullback candidate. Research only; never places orders."""
import csv
import json
import os
import time
from datetime import datetime, timezone

from download_okx_candles import get_page
from download_okx_funding_archive import add_archive_rates
from indicator_features import build_features
from backtest_frozen_indicators import simulate, summarize

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
TF = "4H"
BAR_MS = 4 * 60 * 60 * 1000
FUNDING_MS = 8 * 60 * 60 * 1000
WARMUP_START = "2024-10-16T00:00:00Z"
TEST_START = "2024-11-26T00:00:00Z"
TEST_END = "2025-11-26T00:00:00Z"
OUT = "ai-trend-pullback-results"


def ms(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def iso(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()


def download_candles(inst, start, end):
    rows = {}
    cursor = None
    pages = 0
    while True:
        params = {"instId": inst, "bar": "4Hutc", "limit": "100"}
        if cursor is not None:
            params["after"] = str(cursor)
        batch = get_page(params)
        pages += 1
        if not batch:
            break
        oldest = min(int(x[0]) for x in batch)
        for x in batch:
            t = int(x[0])
            if start <= t < end and len(x) >= 9 and x[8] == "1":
                rows[t] = x
        if oldest <= start:
            break
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"OHLCV pagination stalled for {inst}")
        cursor = oldest
        if pages > 1000:
            raise RuntimeError(f"OHLCV pagination safety stop for {inst}")
    out = []
    for t, x in sorted(rows.items()):
        out.append({
            "timestamp_ms": t, "open": float(x[1]), "high": float(x[2]),
            "low": float(x[3]), "close": float(x[4]),
            "volume_quote": float(x[7])
        })
    expected = list(range(start, end, BAR_MS))
    got = [x["timestamp_ms"] for x in out]
    if got != expected:
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        raise RuntimeError(f"Invalid 4H candle coverage for {inst}: got={len(got)} expected={len(expected)} missing={len(missing)} extra={len(extra)}")
    return out, pages


def download_funding(inst, start, end):
    rates = {}
    add_archive_rates(inst, start, end, rates)
    expected = list(range(start, end, FUNDING_MS))
    normalized = {}
    max_drift = 0
    for actual, item in rates.items():
        nearest = min(expected, key=lambda x: abs(x - actual))
        drift = abs(nearest - actual)
        if drift > 30000 or nearest in normalized:
            raise RuntimeError(f"Funding alignment failure for {inst}: timestamp={actual}, drift={drift}")
        normalized[nearest] = float(item["rate"])
        max_drift = max(max_drift, drift)
    missing = sorted(set(expected) - set(normalized))
    if missing:
        raise RuntimeError(f"Funding coverage gap for {inst}: missing {len(missing)} of {len(expected)}")
    return normalized, max_drift


def adx_wilder(rows, period=14):
    n = len(rows)
    high = [float(x["high"]) for x in rows]
    low = [float(x["low"]) for x in rows]
    close = [float(x["close"]) for x in rows]
    tr = [0.0] * n
    plus = [0.0] * n
    minus = [0.0] * n
    for i in range(1, n):
        up = high[i] - high[i-1]
        down = low[i-1] - low[i]
        plus[i] = up if up > down and up > 0 else 0.0
        minus[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    out = [None] * n
    if n <= period * 2:
        return out
    sm_tr = sum(tr[1:period+1])
    sm_plus = sum(plus[1:period+1])
    sm_minus = sum(minus[1:period+1])
    dx = [None] * n
    for i in range(period, n):
        if i > period:
            sm_tr = sm_tr - sm_tr/period + tr[i]
            sm_plus = sm_plus - sm_plus/period + plus[i]
            sm_minus = sm_minus - sm_minus/period + minus[i]
        pdi = 100.0 * sm_plus / sm_tr if sm_tr else 0.0
        mdi = 100.0 * sm_minus / sm_tr if sm_tr else 0.0
        denom = pdi + mdi
        dx[i] = 100.0 * abs(pdi-mdi) / denom if denom else 0.0
    first = period * 2 - 1
    if first >= n:
        return out
    seed = [dx[i] for i in range(period, first+1) if dx[i] is not None]
    if len(seed) != period:
        return out
    out[first] = sum(seed) / period
    for i in range(first+1, n):
        out[i] = (out[i-1] * (period-1) + dx[i]) / period
    return out


def write_csv(path, records):
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


def main():
    warm, start, end = ms(WARMUP_START), ms(TEST_START), ms(TEST_END)
    os.makedirs(OUT, exist_ok=True)
    all_trades, summaries, quality = [], [], {}
    for symbol in SYMBOLS:
        print(f"Downloading {symbol} 4H candles and funding", flush=True)
        rows, pages = download_candles(symbol, warm, end)
        fmap, drift = download_funding(symbol, warm, end)
        funding_stamps = sorted(fmap)
        contiguous = all(b-a == FUNDING_MS for a,b in zip(funding_stamps, funding_stamps[1:]))
        if not contiguous:
            raise RuntimeError(f"Funding sequence is not contiguous for {symbol}")
        features = build_features(rows)
        adx = adx_wilder(rows, 14)
        for i, feat in enumerate(features):
            feat["ema20_bounce_short_adx25"] = bool(
                feat.get("ema20_bounce_short") and adx[i] is not None and adx[i] >= 25.0
            )
            feat["adx14"] = adx[i]
        trades, invalid = simulate(
            rows, features, TF, "never_true", "ema20_bounce_short_adx25",
            "SWAP", symbol.replace("-USDT-SWAP", ""), "ai_ema20_bounce_adx25_4h",
            "base", "independent_2024_2025", start, end, fmap,
            funding_stamps[0], contiguous
        )
        all_trades.extend(trades)
        m = summarize(trades, invalid)
        summaries.append({
            "aggregation_level": "SYMBOL", "market": "SWAP",
            "symbol": symbol.replace("-USDT-SWAP", ""), "timeframe": TF,
            "direction": "SHORT", "strategy": "ema20_bounce_adx25",
            "period": "independent_2024_2025", **m
        })
        quality[symbol] = {
            "candles_including_warmup": len(rows), "expected_candles": (end-warm)//BAR_MS,
            "first_candle_utc": iso(rows[0]["timestamp_ms"]),
            "last_candle_utc": iso(rows[-1]["timestamp_ms"]),
            "candle_gaps": 0, "funding_records": len(fmap),
            "expected_funding_records": (end-warm)//FUNDING_MS,
            "funding_contiguous": contiguous, "max_funding_timestamp_drift_ms": drift,
            "closed_trades": m["trades_closed"], "invalid_funding_trades": invalid
        }
        print(f"{symbol}: {m['trades_closed']} closed, net {m['net_R']}R, PF {m['profit_factor']}", flush=True)

    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid_total = sum(1 for t in all_trades if t.get("funding_valid") is False)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "market": "SWAP", "symbol": "ALL",
        "timeframe": TF, "direction": "SHORT", "strategy": "ema20_bounce_adx25",
        "period": "independent_2024_2025", **summarize(all_trades, invalid_total)
    })
    monthly = {}
    for t in all_trades:
        if not t["closed"]:
            continue
        month = t["exit_time_utc"][:7]
        key = (t["symbol"], month)
        monthly.setdefault(key, []).append(t)
    monthly_rows = []
    for (sym, month), group in sorted(monthly.items()):
        sm = summarize(group, sum(1 for x in group if x.get("funding_valid") is False))
        monthly_rows.append({"symbol": sym, "month_utc": month, **sm})

    report = {
        "candidate_id": "AI_EMA20_PULLBACK_ADX25_SHORT_4H_ALL5",
        "status": "INDEPENDENT_TEST_COMPLETE",
        "market": "OKX USDT-SWAP Futures", "timeframe": TF, "direction": "SHORT",
        "warmup_start_utc": WARMUP_START,
        "test_start_utc_inclusive": TEST_START, "test_end_utc_exclusive": TEST_END,
        "signal": "On a closed 4H candle: close < EMA20 < EMA50 < EMA200; candle high touches or exceeds EMA20 and closes below EMA20; Wilder ADX(14) >= 25.",
        "entry": "Next 4H candle open",
        "risk": "Stop distance 1.5 * Wilder ATR(14) from actual next-open entry; fixed target 2R; stop-first on same-candle ambiguity.",
        "costs": "0.05% taker fee and 0.02% slippage per side, applied by frozen backtest engine.",
        "funding": "Actual historical OKX funding timestamps; positive funding received by SHORT. Missing records fail closed.",
        "position_policy": "One open position per symbol; each symbol replayed independently; no daily entry cap.",
        "parameters_frozen": True, "parameter_search": False, "orders_generated": False,
        "data_quality": quality, "summary": summaries,
        "limitations": [
            "This is a newly frozen research candidate, not an established profitable strategy.",
            "The 2024-2025 period is an independent replay window; positive results would still require a second untouched forward period and a separate paper approval.",
            "Historical OHLCV does not model order-book depth, liquidation, market impact, or live execution."
        ]
    }
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    write_csv(os.path.join(OUT, "trades.csv"), all_trades)
    write_csv(os.path.join(OUT, "summary.csv"), summaries)
    write_csv(os.path.join(OUT, "monthly_summary.csv"), monthly_rows)
    print(json.dumps({"candidate_id": report["candidate_id"], "summary": summaries, "invalid_funding_trades": invalid_total}, ensure_ascii=False, indent=2), flush=True)
    if invalid_total:
        raise SystemExit("Funding validation failed; result must not be interpreted.")


if __name__ == "__main__":
    main()
