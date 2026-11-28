#!/usr/bin/env python3
"""Frozen independent MFI50 + EMA200 4H research candidate. No orders."""
import csv, json, os
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
OUT = "ai-mfi50-ema200-results"

def ms(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)

def iso(t):
    return datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()

def download_candles(inst, start, end):
    rows, cursor, pages = {}, None, 0
    while True:
        params = {"instId": inst, "bar": TF, "limit": "100"}
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
    expected = list(range(start, end, BAR_MS))
    if sorted(rows) != expected:
        missing = len(set(expected) - set(rows))
        raise RuntimeError(f"Invalid 4H coverage {inst}: got {len(rows)}, expected {len(expected)}, missing {missing}")
    out = []
    for t, x in sorted(rows.items()):
        out.append({
            "timestamp_ms": t, "open": float(x[1]), "high": float(x[2]),
            "low": float(x[3]), "close": float(x[4]),
            "volume_currency": float(x[6]), "volume_quote": float(x[7])
        })
    return out, pages

def add_mfi_signal_features(rows, features):
    # Match the EMA200 and ATR smoothing used by the prior corrected MFI study
    # (pandas ewm with adjust=False), rather than the separate Wilder-seeded helper.
    alpha_ema = 2.0 / 201.0
    alpha_atr = 1.0 / 14.0
    ema_prev = float(rows[0]["close"])
    tr_prev = float(rows[0]["high"]) - float(rows[0]["low"])
    for i, r in enumerate(rows):
        close = float(r["close"])
        high, low = float(r["high"]), float(r["low"])
        if i:
            prev_close = float(rows[i-1]["close"])
            tr = max(high-low, abs(high-prev_close), abs(low-prev_close))
            tr_prev = (1.0-alpha_atr)*tr_prev + alpha_atr*tr
            ema_prev = alpha_ema*close + (1.0-alpha_ema)*ema_prev
        features[i]["ema200"] = ema_prev if i >= 199 else None
        features[i]["atr14"] = tr_prev if i >= 13 else None

    positive, negative = [], []
    typical = []
    for r in rows:
        typical.append((float(r["high"]) + float(r["low"]) + float(r["close"])) / 3.0)
    for i, r in enumerate(rows):
        flow = typical[i] * float(r["volume_currency"])
        if i == 0 or typical[i] == typical[i-1]:
            positive.append(0.0); negative.append(0.0)
        elif typical[i] > typical[i-1]:
            positive.append(flow); negative.append(0.0)
        else:
            positive.append(0.0); negative.append(flow)
    mfi = [None] * len(rows)
    for i in range(13, len(rows)):
        pos, neg = sum(positive[i-13:i+1]), sum(negative[i-13:i+1])
        if neg == 0:
            mfi[i] = 100.0 if pos > 0 else 50.0
        elif pos == 0:
            mfi[i] = 0.0
        else:
            mfi[i] = 100.0 - 100.0 / (1.0 + pos / neg)
    for i, f in enumerate(features):
        prev = mfi[i-1] if i else None
        now = mfi[i]
        ready = prev is not None and now is not None and f.get("ema200") is not None
        f["mfi14"] = now
        f["mfi50_ema200_long"] = bool(ready and prev <= 50.0 and now > 50.0 and f["close"] > f["ema200"])
        f["mfi50_ema200_short"] = bool(ready and prev >= 50.0 and now < 50.0 and f["close"] < f["ema200"])
    return features

def write_csv(path, records):
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader(); w.writerows(records)

def main():
    warm, start, end = ms(WARMUP_START), ms(TEST_START), ms(TEST_END)
    os.makedirs(OUT, exist_ok=True)
    all_trades, summaries, quality = [], [], {}
    for symbol in SYMBOLS:
        print(f"Downloading {symbol} 4H candles + historical funding", flush=True)
        rows, pages = download_candles(symbol, warm, end)
        write_csv(os.path.join(OUT, symbol.replace("-USDT-SWAP", "_USDT_SWAP") + "_4H.csv"), rows)
        rates = {}
        add_archive_rates(symbol, warm, end, rates)
        funding = [{"funding_time_ms": int(t), "rate": float(v["rate"])} for t, v in sorted(rates.items())]
        expected_funding = list(range(warm, end, FUNDING_MS))
        actual_funding = [x["funding_time_ms"] for x in funding]
        if actual_funding != expected_funding:
            raise RuntimeError(f"Funding coverage gap for {symbol}: got {len(actual_funding)}, expected {len(expected_funding)}")
        funding_path = os.path.join(OUT, symbol.replace("-", "_") + "_funding.csv")
        write_csv(funding_path, funding)
        fmap = {x["funding_time_ms"]: x["rate"] for x in funding}
        funding_stamps = sorted(fmap)
        contiguous = all(b-a == FUNDING_MS for a,b in zip(funding_stamps, funding_stamps[1:]))
        if not contiguous:
            raise RuntimeError(f"Non-contiguous funding for {symbol}")
        features = add_mfi_signal_features(rows, build_features(rows))
        trades, invalid = simulate(
            rows, features, TF, "mfi50_ema200_long", "mfi50_ema200_short",
            "SWAP", symbol.replace("-USDT-SWAP", ""), "mfi50_ema200",
            "base", "independent_2024_2025", start, end, fmap,
            funding_stamps[0], contiguous
        )
        all_trades.extend(trades)
        sm = summarize(trades, invalid)
        summaries.append({
            "aggregation_level": "SYMBOL", "market": "SWAP",
            "symbol": symbol.replace("-USDT-SWAP", ""), "timeframe": TF,
            "direction": "BOTH", "strategy": "mfi50_ema200", "period": "independent_2024_2025", **sm
        })
        quality[symbol] = {
            "candles": len(rows), "expected_candles": (end-warm)//BAR_MS,
            "first_candle_utc": iso(rows[0]["timestamp_ms"]),
            "last_candle_utc": iso(rows[-1]["timestamp_ms"]),
            "candle_gaps": 0, "funding_records": len(funding),
            "expected_funding_records": len(expected_funding),
            "funding_contiguous": contiguous, "closed_trades": sm["trades_closed"],
            "invalid_funding_trades": invalid, "download_pages": pages
        }
        print(f"{symbol}: closed={sm['trades_closed']} net_R={sm['net_R']} PF={sm['profit_factor']}", flush=True)

    all_trades.sort(key=lambda t: (t["exit_time_utc"] or "9999", t["entry_time_utc"]))
    invalid_total = sum(1 for t in all_trades if t.get("funding_valid") is False)
    aggregate = summarize(all_trades, invalid_total)
    summaries.append({
        "aggregation_level": "ALL_SYMBOLS", "market": "SWAP", "symbol": "ALL",
        "timeframe": TF, "direction": "BOTH", "strategy": "mfi50_ema200",
        "period": "independent_2024_2025", **aggregate
    })
    report = {
        "candidate_id": "AI_MFI50_EMA200_4H_ALL5",
        "status": "INDEPENDENT_TEST_COMPLETE",
        "market": "OKX USDT-SWAP Futures", "timeframe": TF, "symbols": [s.replace("-USDT-SWAP","") for s in SYMBOLS],
        "warmup_start_utc": WARMUP_START, "test_start_utc_inclusive": TEST_START,
        "test_end_utc_exclusive": TEST_END,
        "signal": "On a closed 4H candle: MFI(14) crosses above 50 while close is above EMA200 for LONG; crosses below 50 while close is below EMA200 for SHORT.",
        "entry": "Next 4H candle open",
        "risk": "Wilder ATR(14) stop distance 1.5x from actual entry; fixed target 2R; stop-first on same-candle ambiguity; gap-through stop exits at open.",
        "costs": "0.05% taker fee and 0.02% slippage per side.",
        "funding": "Historical OKX funding at exact settlement timestamps; missing or misaligned records fail closed.",
        "position_policy": "One position per symbol; each symbol replayed independently.",
        "parameters_frozen": True, "parameter_search": False, "orders_generated": False,
        "data_quality": quality, "summary": summaries,
        "limitations": [
            "Candidate was selected from a separate 2025-2026 screening archive; this 2024-2025 replay is an independent historical regime check, not a future guarantee.",
            "Only OHLCV and funding are modeled; order-book depth, liquidation, market impact and live fills are not.",
            "A positive result requires a separate forward paper-trading period before any deployment decision."
        ]
    }
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2); f.write("\n")
    write_csv(os.path.join(OUT, "trades.csv"), all_trades)
    write_csv(os.path.join(OUT, "summary.csv"), summaries)
    if invalid_total:
        raise SystemExit("Funding validation failed; result must not be interpreted.")
    print(json.dumps({"candidate_id": report["candidate_id"], "summary": summaries}, ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()
