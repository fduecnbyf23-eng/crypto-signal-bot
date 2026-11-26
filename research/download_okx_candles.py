#!/usr/bin/env python3
"""Download exact-range closed OKX candles for offline research only."""
import argparse, csv, json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com/api/v5/market/history-candles"
SPOT = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
SWAPS = [f"{s}-SWAP" for s in SPOT]
TIMEFRAMES = {"15m": 900000, "1H": 3600000, "4H": 14400000}
FIELDS = ["timestamp_ms", "utc_time", "open", "high", "low", "close",
          "volume", "volume_currency", "volume_quote", "confirm"]
_last_request = 0.0

def parse_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Dates must include a UTC timezone, e.g. 2025-08-12T00:00:00Z")
    return dt.astimezone(timezone.utc)

def get_page(params):
    global _last_request
    wait = 0.12 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-Research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _last_request = time.monotonic()
            if payload.get("code") != "0":
                raise RuntimeError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
            return payload.get("data", [])
        except Exception:
            if attempt == 5:
                raise
            time.sleep(min(2 ** attempt, 20))
    return []

def download(inst_id, bar, start_ms, end_ms):
    rows, cursor, pages = {}, end_ms, 0
    while True:
        batch = get_page({"instId": inst_id, "bar": bar, "limit": "100", "after": str(cursor)})
        pages += 1
        if not batch:
            break
        oldest = min(int(row[0]) for row in batch)
        for row in batch:
            ts = int(row[0])
            if start_ms <= ts < end_ms and row[8] == "1":
                rows[ts] = row
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise RuntimeError(f"Pagination did not move backward: {inst_id} {bar}")
        cursor = oldest
        if pages > 2000:
            raise RuntimeError("Safety stop: unexpectedly many pages")
    return [rows[k] for k in sorted(rows)], pages

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-utc", required=True)
    ap.add_argument("--end-utc", required=True, help="Exclusive end boundary")
    ap.add_argument("--out", default="research-data")
    args = ap.parse_args()
    start, end = parse_utc(args.start_utc), parse_utc(args.end_utc)
    if start >= end:
        ap.error("--start-utc must be earlier than --end-utc")
    start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "source": "OKX public market history-candles API",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_utc_inclusive": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "closed_candles_only": True,
        "instruments": {},
        "note": "Research only. Public market-data endpoints; no credentials and no order endpoints."
    }
    jobs = [(x, tf) for x in SWAPS for tf in TIMEFRAMES]
    for index, (inst_id, bar) in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {inst_id} {bar}", flush=True)
        candles, pages = download(inst_id, bar, start_ms, end_ms)
        expected = (end_ms - start_ms) // TIMEFRAMES[bar]
        if len(candles) != expected:
            raise RuntimeError(
                f"Incomplete candle coverage for {inst_id} {bar}: "
                f"expected {expected}, received {len(candles)}. Refusing to backtest partial data."
            )
        if int(candles[0][0]) != start_ms or int(candles[-1][0]) != end_ms - TIMEFRAMES[bar]:
            raise RuntimeError(
                f"Unexpected candle boundaries for {inst_id} {bar}: "
                f"{candles[0][0]}..{candles[-1][0]}, expected {start_ms}..{end_ms-TIMEFRAMES[bar]}"
            )
        path = os.path.join(args.out, f"{inst_id.replace('-', '_')}_{bar}.csv")
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            for row in candles:
                ts = int(row[0])
                writer.writerow([
                    ts, datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                    *row[1:8], row[8]
                ])
        manifest["instruments"][f"{inst_id}:{bar}"] = {
            "file": os.path.basename(path), "candles": len(candles), "expected_candles": expected,
            "pages": pages, "first_timestamp_ms": int(candles[0][0]),
            "last_timestamp_ms": int(candles[-1][0])
        }
        print(f"  saved {len(candles)} / {expected} closed candles ({pages} pages)", flush=True)
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    print(f"Completed: {len(jobs)} complete instrument/timeframe datasets.", flush=True)

if __name__ == "__main__":
    main()
