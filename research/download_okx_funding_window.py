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
        swap = inst  # SYMBOLS already contains the -SWAP suffix
        print(f"[{i}/{len(SYMBOLS)}] {swap}", flush=True)
        rates = {}
        add_archive_rates(swap, start_ms, end_ms, rates)
        stamps = sorted(rates)
        expected = list(range(start_ms, end_ms, 8 * 60 * 60 * 1000))
        if len(stamps) != len(expected) or len(set(stamps)) != len(expected):
            raise RuntimeError(f"Funding record count/uniqueness failure for {swap}: records={len(stamps)}, expected={len(expected)}")
        # OKX archive timestamps can differ from the nominal 8h settlement grid by a few seconds.
        # Match one-to-one within a strict 30s tolerance; preserve source timestamps for audit.
        normalized = []
        used = set()
        max_abs_drift_ms = 0
        for actual_ts in stamps:
            nearest = min(expected, key=lambda x: abs(x - actual_ts))
            drift = actual_ts - nearest
            if abs(drift) > 30_000 or nearest in used:
                raise RuntimeError(f"Funding timestamp cannot be safely aligned for {swap}: {actual_ts}, drift_ms={drift}")
            used.add(nearest)
            max_abs_drift_ms = max(max_abs_drift_ms, abs(drift))
            item = dict(rates[actual_ts])
            item["source_funding_time_ms"] = actual_ts
            item["source_utc_time"] = item["utc_time"]
            item["funding_time_ms"] = nearest
            item["utc_time"] = datetime.fromtimestamp(nearest/1000, timezone.utc).isoformat()
            normalized.append(item)
        missing = sorted(set(expected) - used)
        if missing:
            raise RuntimeError(f"Funding coverage gap for {swap}: missing={len(missing)}")
        name = swap.replace("-", "_") + "_funding.csv"
        rows = sorted(normalized, key=lambda x: x["funding_time_ms"])
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["funding_time_ms", "utc_time", "rate", "rate_field", "source_funding_time_ms", "source_utc_time"])
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
