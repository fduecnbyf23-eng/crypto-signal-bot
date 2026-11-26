#!/usr/bin/env python3
"""Download exact 40-day pre-test 1H SWAP warm-up candles for EMA200. No trading."""
import csv
import json
import os
from datetime import datetime, timezone

from download_okx_candles_window import download_window, to_ms
from download_okx_candles import SWAPS, FIELDS

START_UTC = "2024-10-17T00:00:00Z"
END_UTC = "2024-11-26T00:00:00Z"


def main():
    start_ms, end_ms = to_ms(START_UTC), to_ms(END_UTC)
    if end_ms - start_ms != 40 * 86400000:
        raise SystemExit("Warm-up must be exactly 40 days")
    out = "ema-macd-warmup"
    os.makedirs(out, exist_ok=True)
    manifest = {
        "source": "OKX public market history-candles API",
        "timeframe": "1H",
        "start_utc": START_UTC,
        "end_utc_exclusive": END_UTC,
        "purpose": "Indicator warm-up only; no trades before independent test window.",
        "instruments": {}
    }
    for index, inst_id in enumerate(SWAPS, 1):
        print(f"[{index}/5] {inst_id} 1H warm-up", flush=True)
        candles, pages = download_window(inst_id, start_ms, end_ms)
        if len(candles) != 960:
            raise SystemExit(f"{inst_id}: expected 960 closed candles, got {len(candles)}")
        timestamps = [int(x[0]) for x in candles]
        if timestamps[0] != start_ms or timestamps[-1] != end_ms - 3600000:
            raise SystemExit(f"{inst_id}: unexpected warm-up boundaries")
        if any(b-a != 3600000 for a,b in zip(timestamps,timestamps[1:])):
            raise SystemExit(f"{inst_id}: warm-up candle gap or duplicate")
        filename = f"{inst_id.replace('-', '_')}_1H.csv"
        with open(os.path.join(out, filename), "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(FIELDS)
            for row in candles:
                ts = int(row[0])
                writer.writerow([
                    ts, datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                    *row[1:8], row[8]
                ])
        manifest["instruments"][inst_id] = {
            "file": filename, "candles": len(candles), "pages": pages,
            "first_timestamp_ms": timestamps[0], "last_timestamp_ms": timestamps[-1],
            "gaps": 0
        }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("EMA_MACD_WARMUP_ARCHIVE_OK 4800 candles across 5 SWAP instruments", flush=True)


if __name__ == "__main__":
    main()
