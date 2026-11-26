#!/usr/bin/env python3
"""Fail-closed audit for the fixed 2024-11-26 to 2025-11-26 1H archive."""
import csv
import json
import os
from datetime import datetime, timezone

START = int(datetime(2024, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2025, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 60 * 60 * 1000
EIGHT_HOURS = 8 * HOUR
SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    folder = "independent-1h-data"
    report = {
        "start_utc": datetime.fromtimestamp(START/1000, timezone.utc).isoformat(),
        "end_utc_exclusive": datetime.fromtimestamp(END/1000, timezone.utc).isoformat(),
        "candle_sets": {}, "funding_sets": {}, "all_valid": True
    }
    manifest = json.load(open(os.path.join(folder, "manifest.json"), encoding="utf-8"))
    if manifest.get("timeframe") != "1H" or len(manifest.get("instruments", {})) != 10:
        raise SystemExit("Candle manifest has unexpected timeframe or instrument count")
    for symbol in SYMBOLS:
        for swap in (False, True):
            inst = f"{symbol}-USDT-SWAP" if swap else f"{symbol}-USDT"
            filename = f"{symbol}_USDT{'_SWAP' if swap else ''}_1H.csv"
            rows = read_rows(os.path.join(folder, filename))
            ts = [int(r["timestamp_ms"]) for r in rows]
            gaps = sum(1 for a,b in zip(ts, ts[1:]) if b-a != HOUR)
            valid = (
                len(rows) == 8760 and ts[0] == START and ts[-1] == END-HOUR
                and len(set(ts)) == len(ts) and gaps == 0
                and all(r["confirm"] == "1" for r in rows)
                and all(float(r["low"]) <= min(float(r["open"]),float(r["close"]))
                        <= max(float(r["open"]),float(r["close"])) <= float(r["high"]) for r in rows)
            )
            report["candle_sets"][inst] = {
                "file": filename, "candles": len(rows),
                "first_utc": rows[0]["utc_time"] if rows else None,
                "last_utc": rows[-1]["utc_time"] if rows else None,
                "interval_gaps": gaps, "valid": valid
            }
            if not valid:
                report["all_valid"] = False

    fmanifest = json.load(open(os.path.join(folder, "funding_manifest.json"), encoding="utf-8"))
    if len(fmanifest.get("instruments", {})) != 5:
        raise SystemExit("Funding manifest has unexpected instrument count")
    for symbol in SYMBOLS:
        inst = f"{symbol}-USDT-SWAP"
        filename = f"{symbol}_USDT_SWAP_funding.csv"
        rows = read_rows(os.path.join(folder, filename))
        ts = [int(r["funding_time_ms"]) for r in rows]
        missing = [t for t in range(START, END, EIGHT_HOURS) if t not in set(ts)]
        valid = (
            len(rows) == 1095 and ts[0] == START and ts[-1] == END-EIGHT_HOURS
            and len(set(ts)) == len(ts) and not missing
        )
        report["funding_sets"][inst] = {
            "file": filename, "records": len(rows), "missing_expected": len(missing),
            "first_utc": rows[0]["utc_time"] if rows else None,
            "last_utc": rows[-1]["utc_time"] if rows else None, "valid": valid
        }
        if not valid:
            report["all_valid"] = False

    with open(os.path.join(folder, "independent_1h_audit_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if not report["all_valid"]:
        raise SystemExit("Independent 1H archive failed audit")
    print("INDEPENDENT_1H_AUDIT_OK candles=87600 funding_records=5475 gaps=0", flush=True)


if __name__ == "__main__":
    main()
