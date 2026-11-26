#!/usr/bin/env python3
"""Download fixed historical 8-hour OKX SWAP funding window from public monthly archives."""
import argparse
import csv
import json
import os
from datetime import datetime, timezone

from download_okx_funding_archive import SYMBOLS, add_archive_rates


def to_ms(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Date-time must include UTC timezone.")
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-utc", default="2024-11-26T00:00:00Z")
    ap.add_argument("--end-utc", default="2025-11-26T00:00:00Z")
    ap.add_argument("--out", default="independent-1h-data")
    args = ap.parse_args()
    start_ms, end_ms = to_ms(args.start_utc), to_ms(args.end_utc)
    if end_ms <= start_ms or end_ms - start_ms != 365 * 86400000:
        raise SystemExit("This frozen independent funding window must be exactly 365 days.")
    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "source": "OKX public monthly market-data-history funding archive",
        "start_utc": datetime.fromtimestamp(start_ms/1000, timezone.utc).isoformat(),
        "end_utc_exclusive": datetime.fromtimestamp(end_ms/1000, timezone.utc).isoformat(),
        "expected_interval_hours": 8,
        "instruments": {}
    }
    for i, inst in enumerate(SYMBOLS, 1):
        swap = inst + "-SWAP"
        print(f"[{i}/{len(SYMBOLS)}] {swap}", flush=True)
        rates = {}
        add_archive_rates(swap, start_ms, end_ms, rates)
        stamps = sorted(rates)
        expected = list(range(start_ms, end_ms, 8 * 60 * 60 * 1000))
        missing = [ts for ts in expected if ts not in rates]
        if not stamps or missing:
            raise RuntimeError(f"Funding coverage gap for {swap}: records={len(stamps)}, missing={len(missing)}")
        if stamps[0] < start_ms or stamps[-1] >= end_ms:
            raise RuntimeError(f"Funding timestamps outside requested window for {swap}")
        name = swap.replace("-", "_") + "_funding.csv"
        rows = [rates[ts] for ts in stamps]
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["funding_time_ms", "utc_time", "rate", "rate_field"])
            w.writeheader()
            w.writerows(rows)
        manifest["instruments"][swap] = {
            "file": name, "records": len(rows),
            "first_ms": stamps[0], "last_ms": stamps[-1],
            "missing_expected_records": len(missing)
        }
        print(f"  saved {len(rows)} funding records; no 8h gaps", flush=True)
    with open(os.path.join(args.out, "funding_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("Completed fixed historical funding archive.", flush=True)


if __name__ == "__main__":
    main()
