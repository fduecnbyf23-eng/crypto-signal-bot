#!/usr/bin/env python3
"""Download closed OKX candles for offline strategy research. No trading actions."""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://www.okx.com/api/v5/market/history-candles"
SPOT = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
SWAPS = [f"{s}-SWAP" for s in SPOT]
TIMEFRAMES = ["15m", "1H", "4H", "1Dutc"]
FIELDS = ["timestamp_ms", "utc_time", "open", "high", "low", "close",
          "volume", "volume_currency", "volume_quote", "confirm"]
_last_request = 0.0


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


def download(inst_id, bar, cutoff_ms):
    rows = {}
    cursor = None
    pages = 0
    while True:
        params = {"instId": inst_id, "bar": bar, "limit": "100"}
        if cursor is not None:
            params["after"] = str(cursor)
        batch = get_page(params)
        pages += 1
        if not batch:
            break
        oldest = min(int(row[0]) for row in batch)
        for row in batch:
            ts = int(row[0])
            if ts >= cutoff_ms and row[8] == "1":
                rows[ts] = row
        if oldest <= cutoff_ms:
            break
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"Pagination did not move backward: {inst_id} {bar}")
        cursor = oldest
        if pages > 2000:
            raise RuntimeError("Safety stop: unexpectedly many pages")
    return [rows[k] for k in sorted(rows)], pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--out", default="research-data")
    args = parser.parse_args()
    if not 30 <= args.days <= 365:
        parser.error("--days must be between 30 and 365")

    os.makedirs(args.out, exist_ok=True)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    cutoff_ms = int(start.timestamp() * 1000)
    manifest = {
        "source": "OKX public market history-candles API",
        "downloaded_at_utc": end.isoformat(),
        "requested_days": args.days,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "closed_candles_only": True,
        "instruments": {},
        "note": "Research data only. No API credentials and no order endpoints are used."
    }

    jobs = [(x, tf) for x in SPOT + SWAPS for tf in TIMEFRAMES]
    for index, (inst_id, bar) in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {inst_id} {bar}", flush=True)
        candles, pages = download(inst_id, bar, cutoff_ms)
        path = os.path.join(args.out, f"{inst_id.replace('-', '_')}_{bar}.csv")
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(FIELDS)
            for row in candles:
                ts = int(row[0])
                writer.writerow([
                    ts, datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(),
                    *row[1:8], row[8]
                ])
        manifest["instruments"][f"{inst_id}:{bar}"] = {
            "file": os.path.basename(path),
            "candles": len(candles),
            "pages": pages,
            "first_timestamp_ms": int(candles[0][0]) if candles else None,
            "last_timestamp_ms": int(candles[-1][0]) if candles else None,
        }
        print(f"  saved {len(candles)} closed candles ({pages} pages)", flush=True)

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    total = sum(x["candles"] for x in manifest["instruments"].values())
    print(f"Completed: {total} closed candles across {len(jobs)} instrument/timeframe sets.", flush=True)


if __name__ == "__main__":
    main()
