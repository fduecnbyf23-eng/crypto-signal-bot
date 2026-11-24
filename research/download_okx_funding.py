#!/usr/bin/env python3
"""Download public OKX realized funding-rate history for research only."""
import argparse, csv, json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
BASE = "https://www.okx.com/api/v5/public/funding-rate-history"
_last = 0.0

def fetch(inst_id, params):
    global _last
    delay = 0.22 - (time.monotonic() - _last)
    if delay > 0: time.sleep(delay)
    url = BASE + "?" + urllib.parse.urlencode({"instId": inst_id, "limit": "100", **params})
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-Research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode("utf-8"))
    _last = time.monotonic()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX funding error {payload.get('code')}: {payload.get('msg')}")
    return payload.get("data", [])

def download(inst_id, start_ms, end_ms):
    rows = {}
    cursor = None
    pages = 0
    while True:
        params = {"after": str(cursor)} if cursor is not None else {}
        batch = fetch(inst_id, params)
        pages += 1
        if not batch: break
        oldest = min(int(x["fundingTime"]) for x in batch)
        for x in batch:
            ts = int(x["fundingTime"])
            if start_ms <= ts <= end_ms:
                rate = x.get("realizedRate") if x.get("realizedRate") is not None else x.get("fundingRate")
                if rate is not None:
                    rows[ts] = {"funding_time_ms": ts, "utc_time": datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(), "rate": rate, "rate_field": "realizedRate" if x.get("realizedRate") is not None else "fundingRate"}
        if oldest <= start_ms: break
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"Funding pagination did not move backward: {inst_id}")
        cursor = oldest
        if pages > 20: raise RuntimeError("Safety stop: unexpectedly many funding pages")
    return [rows[k] for k in sorted(rows)], pages

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--out", default="research-data")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    start_ms = int((now - timedelta(days=args.days)).timestamp()*1000)
    end_ms = int(now.timestamp()*1000)
    os.makedirs(args.out, exist_ok=True)
    manifest = {"source": "OKX public funding-rate-history API", "requested_days": args.days, "start_utc": datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(), "end_utc": now.isoformat(), "instruments": {}}
    for i, inst in enumerate(SYMBOLS, 1):
        print(f"[{i}/{len(SYMBOLS)}] {inst} funding", flush=True)
        rows, pages = download(inst, start_ms, end_ms)
        name = inst.replace("-", "_") + "_funding.csv"
        with open(os.path.join(args.out,name),"w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=["funding_time_ms","utc_time","rate","rate_field"])
            w.writeheader(); w.writerows(rows)
        manifest["instruments"][inst] = {"file":name,"records":len(rows),"pages":pages,"first_ms":rows[0]["funding_time_ms"] if rows else None,"last_ms":rows[-1]["funding_time_ms"] if rows else None}
        print(f"  saved {len(rows)} funding records", flush=True)
    with open(os.path.join(args.out,"funding_manifest.json"),"w",encoding="utf-8") as f: json.dump(manifest,f,indent=2)

if __name__ == "__main__": main()
