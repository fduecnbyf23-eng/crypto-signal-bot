#!/usr/bin/env python3
"""Download exact-range historical OKX USDT-SWAP funding from public monthly archives."""
import argparse, csv, io, json, os, time, urllib.parse, urllib.request, zipfile
from datetime import datetime, timezone, timedelta

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
API = "https://www.okx.com/api/v5/public/market-data-history"
REST = "https://www.okx.com/api/v5/public/funding-rate-history"
HK = timezone(timedelta(hours=8))
_last = 0.0

def parse_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Dates must include a UTC timezone")
    return dt.astimezone(timezone.utc)

def get_json(url):
    global _last
    delay = 0.25 - (time.monotonic() - _last)
    if delay > 0:
        time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-Research/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        obj = json.loads(response.read().decode("utf-8"))
    _last = time.monotonic()
    if obj.get("code") != "0":
        raise RuntimeError(f"OKX error {obj.get('code')}: {obj.get('msg')}")
    return obj.get("data", [])

def hk_month_start_ms(ts):
    d = datetime.fromtimestamp(ts/1000, timezone.utc).astimezone(HK)
    local = datetime(d.year, d.month, 1, tzinfo=HK)
    return int(local.astimezone(timezone.utc).timestamp()*1000)

def add_archive_rates(inst, start_ms, archive_end_ms, rates):
    family = inst.removesuffix("-SWAP")
    window_start = hk_month_start_ms(start_ms)
    files = {}
    while window_start < archive_end_ms:
        window_end = min(window_start + 240*86400000, archive_end_ms)
        params = urllib.parse.urlencode({
            "module": "3", "instType": "SWAP", "instFamilyList": family,
            "dateAggrType": "monthly", "begin": str(window_start), "end": str(window_end)
        })
        data = get_json(API + "?" + params)
        archive_items = []
        for group in data:
            if not isinstance(group, dict):
                raise RuntimeError(f"Malformed archive group for {inst}")
            top = group.get("groupDetails", [])
            if top:
                if not isinstance(top, list):
                    raise RuntimeError(f"Malformed groupDetails for {inst}")
                archive_items.extend(top)
            for detail in group.get("details", []):
                if not isinstance(detail, dict):
                    raise RuntimeError(f"Malformed archive detail for {inst}")
                nested = detail.get("groupDetails", [])
                if nested:
                    if not isinstance(nested, list):
                        raise RuntimeError(f"Malformed nested groupDetails for {inst}")
                    archive_items.extend(nested)
        print(f"  archive query {datetime.fromtimestamp(window_start/1000, timezone.utc).date()} "
              f"to {datetime.fromtimestamp(window_end/1000, timezone.utc).date()}: "
              f"{len(archive_items)} files", flush=True)
        for item in archive_items:
            if not isinstance(item, dict):
                raise RuntimeError(f"Malformed archive file entry for {inst}")
            filename, url = item.get("filename"), item.get("url")
            if not filename or not url:
                raise RuntimeError(f"Archive listing missing filename/url for {inst}")
            actual = url.split("?", 1)[0].rsplit("/", 1)[-1]
            if actual != filename:
                raise RuntimeError(f"Archive filename/url mismatch: {filename} != {actual}")
            files[filename] = url
        if window_end >= archive_end_ms:
            break
        next_start = hk_month_start_ms(window_end)
        if next_start <= window_start:
            raise RuntimeError(f"Archive date window did not advance for {inst}")
        window_start = next_start
    for filename, url in sorted(files.items()):
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-Research/1.0"})
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise RuntimeError(f"Expected one CSV in {filename}, got {len(names)}")
            text = zf.read(names[0]).decode("utf-8-sig")
        count = 0
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 3:
                continue
            if row[0] != inst:
                if row[0].lower() in ("instrument_name", "instid", "instrument"):
                    continue
                raise RuntimeError(f"Unexpected instrument {row[0]} in {filename}; expected {inst}")
            try:
                rate, ts = float(row[1]), int(row[2])
            except (ValueError, TypeError):
                raise RuntimeError(f"Malformed funding row in {filename}: {row[:3]}")
            if start_ms <= ts < archive_end_ms:
                rates[ts] = {
                    "funding_time_ms": ts,
                    "utc_time": datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                    "rate": rate, "rate_field": "archive_funding_rate"
                }
                count += 1
        if count == 0:
            raise RuntimeError(f"No in-range funding rows in archive file {filename}")
        print(f"  {filename}: {count} in-range rows", flush=True)

def add_current_month_rest(inst, start_ms, end_ms, rates):
    cursor = None
    while True:
        params = {"instId": inst, "limit": "100"}
        if cursor is not None:
            params["after"] = str(cursor)
        data = get_json(REST + "?" + urllib.parse.urlencode(params))
        if not data:
            break
        oldest = min(int(x["fundingTime"]) for x in data)
        for x in data:
            ts = int(x["fundingTime"])
            if start_ms <= ts < end_ms:
                raw, field = x.get("realizedRate"), "realizedRate"
                if raw is None:
                    raw, field = x.get("fundingRate"), "fundingRate"
                if raw is not None:
                    rates[ts] = {
                        "funding_time_ms": ts,
                        "utc_time": datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                        "rate": float(raw), "rate_field": field
                    }
        if oldest <= start_ms:
            break
        if cursor is not None and oldest >= cursor:
            raise RuntimeError(f"REST pagination did not move backward for {inst}")
        cursor = oldest
        if len(data) < 100:
            break

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-utc", required=True)
    ap.add_argument("--end-utc", required=True, help="Exclusive end boundary")
    ap.add_argument("--out", default="research-data")
    args = ap.parse_args()
    start, end = parse_utc(args.start_utc), parse_utc(args.end_utc)
    if start >= end:
        ap.error("--start-utc must be earlier than --end-utc")
    start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    now_ms = int(datetime.now(timezone.utc).timestamp()*1000)
    archive_end = min(hk_month_start_ms(now_ms), end_ms)
    os.makedirs(args.out, exist_ok=True)
    manifest = {
        "source": "OKX public monthly market-data-history funding archive + public REST for current month only",
        "start_utc_inclusive": start.isoformat(), "end_utc_exclusive": end.isoformat(),
        "archive_end_utc": datetime.fromtimestamp(archive_end/1000, timezone.utc).isoformat(),
        "archive_timezone": "UTC+8", "instruments": {}
    }
    for i, inst in enumerate(SYMBOLS, 1):
        print(f"[{i}/{len(SYMBOLS)}] {inst}", flush=True)
        rates = {}
        if start_ms < archive_end:
            add_archive_rates(inst, start_ms, archive_end, rates)
        if archive_end < end_ms:
            add_current_month_rest(inst, max(start_ms, archive_end), end_ms, rates)
        rows = [rates[k] for k in sorted(rates)]
        expected = (end_ms-start_ms)/(8*3600000)
        coverage = len(rows)/expected if expected else 0
        if coverage < 0.90:
            raise RuntimeError(f"Funding coverage too low for {inst}: {len(rows)} records, approx {coverage:.1%}")
        name = inst.replace("-", "_") + "_funding.csv"
        with open(os.path.join(args.out, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["funding_time_ms", "utc_time", "rate", "rate_field"])
            w.writeheader()
            w.writerows(rows)
        manifest["instruments"][inst] = {
            "file": name, "records": len(rows), "expected_8h_records": round(expected),
            "first_ms": rows[0]["funding_time_ms"], "last_ms": rows[-1]["funding_time_ms"],
            "approx_8h_coverage": round(coverage, 4)
        }
        print(f"  saved {len(rows)} records; approx coverage {coverage:.1%}", flush=True)
    with open(os.path.join(args.out, "funding_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
