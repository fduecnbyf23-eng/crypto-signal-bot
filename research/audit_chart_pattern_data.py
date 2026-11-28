#!/usr/bin/env python3
"""Fail-closed integrity audit for the chart-pattern OKX archive."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
BARS = {"1H": 3_600_000, "4H": 14_400_000}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    root = Path(args.directory)
    manifest = load(root / "manifest.json")
    start_ms, end_ms = manifest["start_ms"], manifest["end_ms"]
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "manifest_days": manifest["days_requested"], "checks": [], "errors": [], "warnings": []}

    for symbol in SYMBOLS:
        stem = symbol.replace("-", "_")
        for bar, step in BARS.items():
            name = f"{stem}_{bar}.json"
            rows = load(root / name)
            ts = [int(row[0]) for row in rows]
            errors = []
            if len(ts) < (manifest["days_requested"] * 24 // (1 if bar == "1H" else 4)) * 0.90:
                errors.append(f"insufficient candle count: {len(ts)}")
            if ts != sorted(set(ts)):
                errors.append("timestamps are not strictly increasing and unique")
            gaps = [(ts[i-1], ts[i]) for i in range(1, len(ts)) if ts[i] - ts[i-1] != step]
            if gaps:
                errors.append(f"{len(gaps)} candle gaps; first={gaps[0]}")
            if not rows or ts[0] < start_ms - step or ts[-1] > end_ms:
                errors.append("candle range outside requested window or empty")
            item = {"file": name, "count": len(rows), "first_ts": ts[0] if ts else None,
                    "last_ts": ts[-1] if ts else None, "gap_count": len(gaps), "errors": errors}
            report["checks"].append(item)
            report["errors"].extend(f"{name}: {e}" for e in errors)

        name = f"{stem}_funding.json"
        rows = load(root / name)
        ts = [int(row["fundingTime"]) for row in rows]
        errors = []
        if not rows:
            errors.append("no funding records")
        if ts != sorted(set(ts)):
            errors.append("funding timestamps are not strictly increasing and unique")
        if rows and (ts[0] > start_ms + 86_400_000 or ts[-1] < end_ms - 86_400_000):
            errors.append("funding coverage does not reach both ends of requested window")
        missing_rates = [row for row in rows if not row.get("realizedRate") and not row.get("fundingRate")]
        if missing_rates:
            errors.append(f"{len(missing_rates)} funding rows lack usable rate")
        large_gaps = [(ts[i-1], ts[i]) for i in range(1, len(ts)) if ts[i] - ts[i-1] > 86_400_000]
        if large_gaps:
            errors.append(f"{len(large_gaps)} funding gaps exceed 24h; first={large_gaps[0]}")
        item = {"file": name, "count": len(rows), "first_ts": ts[0] if ts else None,
                "last_ts": ts[-1] if ts else None, "gaps_over_24h": len(large_gaps), "errors": errors}
        report["checks"].append(item)
        report["errors"].extend(f"{name}: {e}" for e in errors)

    report["passed"] = not report["errors"]
    (root / "audit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "errors": report["errors"]}, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
