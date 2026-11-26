#!/usr/bin/env python3
"""Download a fixed historical window of closed 1H OKX spot and SWAP candles."""
import argparse
import csv
import json
import os
from datetime import datetime, timezone

from download_okx_candles import get_page, SPOT, SWAPS, FIELDS


def to_ms(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Date-time must include UTC timezone, e.g. 2024-11-26T00:00:00Z")
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def download_window(inst_id, start_ms, end_ms):
    rows = {}
    cursor = None
    pages = 0
    while True:
        params = {"instId": inst_id, "bar": "1H", "limit": "100"}
        if cursor is not None:
            params["after"] = str(cursor)
        batch = get_page(params)
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
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"Pagination did not move backward: {inst_id}")
        cursor = oldest
        if pages > 2000:
            raise RuntimeError("Safety stop: unexpectedly many pages")
    return [rows[k] for k in sorted(rows)], pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-utc", default="2024-11-26T00:00:00Z")
    ap.add_argument("--end-utc", default="2025-11-26T00:00:00Z")
    ap.add_argument("--out", default="independent-1h-data")
    args = ap.parse_args()
    start_ms, end_ms = to_ms(args.start_utc), to_ms(args.end_utc)
    if end_ms <= start_ms or end_ms - start_ms != 365 * 86400000:
        raise SystemExit("This frozen independent window must be exactly 365 days.")
    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "source": "OKX public market history-candles API",
        "timeframe": "1H",
        "start_utc": datetime.fromtimestamp(start_ms/1000, timezone.utc).isoformat(),
        "end_utc_exclusive": datetime.fromtimestamp(end_ms/1000, timezone.utc).isoformat(),
        "closed_candles_only": True,
        "instruments": {}
    }
    jobs = [(x, "") for x in SPOT] + [(x + "-SWAP", "_SWAP") for x in SPOT]
    for index, (inst_id, suffix) in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {inst_id} 1H", flush=True)
        candles, pages = download_window(inst_id, start_ms, end_ms)
        if len(candles) < 8500:
            raise RuntimeError(f"Too few candles for {inst_id}: {len(candles)}")
        name = f"{inst_id.replace('-', '_')}_1H.csv"
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            for row in candles:
                ts = int(row[0])
                w.writerow([
                    ts, datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                    *row[1:8], row[8]
                ])
        manifest["instruments"][inst_id] = {
            "file": name, "candles": len(candles), "pages": pages,
            "first_timestamp_ms": int(candles[0][0]),
            "last_timestamp_ms": int(candles[-1][0])
        }
        print(f"  saved {len(candles)} closed candles ({pages} pages)", flush=True)
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("Completed fixed historical 1H candle window.", flush=True)


if __name__ == "__main__":
    main()
