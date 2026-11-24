#!/usr/bin/env python3
"""Download public OKX derivatives statistics for research only.

No API credentials or trading endpoints are used. OKX documents a maximum
of 1,440 recent points for these 4H statistics endpoints (about 240 days).
"""
import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com"
SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
PERIOD = "4H"
PAGE_SIZE = 100
MAX_POINTS = 1440
SPECS = {
    "open_interest": {
        "path": "/api/v5/rubik/stat/contracts/open-interest-history",
        "params": {},
        "columns": ["oi_contracts", "oi_coin", "oi_usd"],
    },
    "taker_volume": {
        "path": "/api/v5/rubik/stat/taker-volume-contract",
        "params": {"unit": "2"},
        "columns": ["taker_sell_volume_usd", "taker_buy_volume_usd"],
    },
    "top_trader_account_ratio": {
        "path": "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader",
        "params": {},
        "columns": ["top_trader_long_short_account_ratio"],
    },
    "top_trader_position_ratio": {
        "path": "/api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
        "params": {},
        "columns": ["top_trader_long_short_position_ratio"],
    },
    "all_trader_account_ratio": {
        "path": "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract",
        "params": {},
        "columns": ["all_trader_long_short_account_ratio"],
    },
}


def request_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CryptoSignalAI-research/1.0", "Accept": "application/json"},
    )
    last_error = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != "0":
                raise RuntimeError(
                    f"OKX error code={payload.get('code')} msg={payload.get('msg')}"
                )
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            if attempt == 5:
                break
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"Request failed after retries: {url}: {last_error}")


def download_metric(inst_id, metric, spec, days):
    rows_by_ts = {}
    cursor = None
    calls = 0
    while len(rows_by_ts) < MAX_POINTS:
        params = {
            "instId": inst_id,
            "period": PERIOD,
            "limit": str(PAGE_SIZE),
            **spec["params"],
        }
        if cursor is not None:
            params["end"] = str(cursor)
        query = urllib.parse.urlencode(params)
        payload = request_json(f"{BASE}{spec['path']}?{query}")
        batch = payload.get("data") or []
        calls += 1
        if not batch:
            break

        oldest_in_page = None
        for row in batch:
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = int(row[0])
            oldest_in_page = ts if oldest_in_page is None else min(oldest_in_page, ts)
            rows_by_ts[ts] = row

        if oldest_in_page is None:
            break
        if cursor is not None and oldest_in_page >= cursor:
            break
        cursor = oldest_in_page
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(0.45)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - days * 24 * 60 * 60 * 1000
    selected = [row for ts, row in rows_by_ts.items() if ts >= cutoff_ms]
    selected.sort(key=lambda row: int(row[0]))

    out = []
    for row in selected:
        record = {"timestamp_ms": int(row[0])}
        record.update({name: row[i + 1] if i + 1 < len(row) else "" for i, name in enumerate(spec["columns"])})
        out.append(record)
    return out, calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, choices=[30, 60, 90, 180, 240], default=240)
    parser.add_argument("--out", default="research-derivatives")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "source": "OKX public Trading Statistics REST API",
        "period": PERIOD,
        "requested_days": args.days,
        "maximum_points_per_metric": MAX_POINTS,
        "note": "The official API limits these 4H endpoints to the latest 1,440 data points. Research only; no credentials or order endpoints.",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "instruments": {},
    }

    for symbol in SYMBOLS:
        inst_id = f"{symbol}-SWAP"
        for metric, spec in SPECS.items():
            print(f"Downloading {inst_id} {metric}", flush=True)
            records, calls = download_metric(inst_id, metric, spec, args.days)
            if not records:
                raise RuntimeError(f"No records returned for {inst_id} {metric}")
            filename = f"{symbol.replace('-', '_')}_SWAP_{metric}_4H.csv"
            path = os.path.join(args.out, filename)
            fieldnames = ["timestamp_ms", *spec["columns"]]
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(records)
            manifest["instruments"].setdefault(inst_id, {})[metric] = {
                "file": filename,
                "records": len(records),
                "api_calls": calls,
                "first_timestamp_ms": records[0]["timestamp_ms"],
                "last_timestamp_ms": records[-1]["timestamp_ms"],
            }
            print(f"  saved {len(records)} rows in {filename}", flush=True)
            time.sleep(0.45)

    with open(os.path.join(args.out, "derivatives_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    print("Download complete.", flush=True)


if __name__ == "__main__":
    main()
