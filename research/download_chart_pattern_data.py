#!/usr/bin/env python3
"""Download a bounded, auditable 90-day OKX USDT-SWAP research dataset.

Read-only public endpoints only. No credentials and no order endpoints.
Funding history is limited by OKX to roughly the latest three months; this
script refuses horizons over 90 days so it cannot silently imply longer coverage.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.okx.com"
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
BARS = {"1H": 3_600_000, "4H": 14_400_000}


def get_json(path: str, params: dict) -> dict:
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "chart-pattern-research/1.0"})
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != "0":
                raise RuntimeError(f"OKX API error: {payload}")
            return payload
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 + attempt * 1.5)
    raise RuntimeError(f"Request failed after retries: {url}: {last_error}")


def download_candles(inst_id: str, bar: str, start_ms: int, end_ms: int) -> list[list]:
    rows: dict[int, list] = {}
    cursor = end_ms + BARS[bar]
    while True:
        payload = get_json("/api/v5/market/history-candles", {
            "instId": inst_id, "bar": bar, "after": str(cursor), "limit": "100"
        })
        batch = payload.get("data", [])
        if not batch:
            break
        oldest = min(int(x[0]) for x in batch)
        for row in batch:
            ts = int(row[0])
            if start_ms <= ts <= end_ms and len(row) >= 9 and row[8] == "1":
                rows[ts] = row
        if oldest <= start_ms or oldest >= cursor:
            break
        cursor = oldest
        time.sleep(0.12)
    return [rows[k] for k in sorted(rows)]


def download_funding(inst_id: str, start_ms: int, end_ms: int) -> list[dict]:
    rows: dict[int, dict] = {}
    cursor = end_ms + 1
    while True:
        payload = get_json("/api/v5/public/funding-rate-history", {
            "instId": inst_id, "after": str(cursor), "limit": "400"
        })
        batch = payload.get("data", [])
        if not batch:
            break
        oldest = min(int(x["fundingTime"]) for x in batch)
        for row in batch:
            ts = int(row["fundingTime"])
            if start_ms <= ts <= end_ms:
                rows[ts] = row
        if oldest <= start_ms or oldest >= cursor:
            break
        cursor = oldest
        time.sleep(0.25)
    return [rows[k] for k in sorted(rows)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", default="chart-pattern-data")
    args = parser.parse_args()
    if not 1 <= args.days <= 90:
        raise SystemExit("Funding archive coverage is limited to about 3 months; --days must be 1..90.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - args.days * 86_400_000
    manifest = {
        "source": "OKX public REST API v5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_ms": start_ms, "end_ms": end_ms, "days_requested": args.days,
        "symbols": SYMBOLS, "timeframes": list(BARS),
        "funding_history_limit_note": "OKX funding-rate-history endpoint supports roughly the latest 3 months; no longer coverage is claimed.",
        "files": {}
    }
    for symbol in SYMBOLS:
        for bar in BARS:
            rows = download_candles(symbol, bar, start_ms, end_ms)
            name = f"{symbol.replace('-', '_')}_{bar}.json"
            (out / name).write_text(json.dumps(rows, separators=(",", ":")), encoding="utf-8")
            manifest["files"][name] = {
                "kind": "closed_candles", "symbol": symbol, "bar": bar,
                "count": len(rows),
                "first_ts": int(rows[0][0]) if rows else None,
                "last_ts": int(rows[-1][0]) if rows else None
            }
        funding = download_funding(symbol, start_ms, end_ms)
        name = f"{symbol.replace('-', '_')}_funding.json"
        (out / name).write_text(json.dumps(funding, separators=(",", ":")), encoding="utf-8")
        manifest["files"][name] = {
            "kind": "funding", "symbol": symbol, "count": len(funding),
            "first_ts": int(funding[0]["fundingTime"]) if funding else None,
            "last_ts": int(funding[-1]["fundingTime"]) if funding else None
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"symbols": len(SYMBOLS), "timeframes": len(BARS),
                      "files": len(manifest["files"]), "days": args.days,
                      "manifest": str(out / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
