#!/usr/bin/env python3
"""Fail-closed structural audit of OKX spot/SWAP candles and SWAP funding."""
import csv, json, os, sys
from collections import Counter
from datetime import datetime, timezone

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
TIMEFRAMES = {"15m": 900000, "1H": 3600000, "4H": 14400000, "1Dutc": 86400000}
FIELDS = {"timestamp_ms", "open", "high", "low", "close", "volume", "volume_quote", "confirm"}

def fail(message):
    raise RuntimeError(message)

def load_candles(path, expected_ms):
    if not os.path.exists(path):
        fail("Missing candle file: " + path)
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not FIELDS.issubset(set(reader.fieldnames or [])):
            fail("Missing required columns in " + path)
        for row in reader:
            ts = int(row["timestamp_ms"])
            if row["confirm"] != "1":
                fail("Unclosed candle in " + path)
            o,h,l,c = (float(row[k]) for k in ("open","high","low","close"))
            vq = float(row["volume_quote"])
            if min(o,h,l,c) <= 0 or h < max(o,c,l) or l > min(o,c,h) or vq < 0:
                fail("Invalid OHLC/quote-volume row in " + path)
            rows.append(ts)
    if len(rows) < 10:
        fail("Too few candles in " + path)
    if rows != sorted(set(rows)):
        fail("Duplicate or unordered timestamps in " + path)
    gaps = sum(1 for a,b in zip(rows, rows[1:]) if b-a != expected_ms)
    return {"candles":len(rows),"first_utc":datetime.fromtimestamp(rows[0]/1000,timezone.utc).isoformat(),
            "last_utc":datetime.fromtimestamp(rows[-1]/1000,timezone.utc).isoformat(),
            "interval_gaps":gaps,"first_ms":rows[0],"last_ms":rows[-1]}

def load_funding(path):
    if not os.path.exists(path):
        fail("Missing funding file: " + path)
    times=[]
    with open(path,newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts=int(row["funding_time_ms"]); rate=float(row["rate"])
            if not (-1.0 < rate < 1.0):
                fail("Implausible funding rate in " + path)
            times.append(ts)
    if len(times)<10 or times != sorted(set(times)):
        fail("Funding is empty/too short, duplicated or unordered: " + path)
    deltas=[(b-a)/3600000 for a,b in zip(times,times[1:])]
    hist={str(k):v for k,v in Counter(round(x,3) for x in deltas).most_common(10)}
    return {"records":len(times),"first_utc":datetime.fromtimestamp(times[0]/1000,timezone.utc).isoformat(),
            "last_utc":datetime.fromtimestamp(times[-1]/1000,timezone.utc).isoformat(),
            "observed_gap_hours_top":hist}

def main():
    folder=sys.argv[1] if len(sys.argv)>1 else "research-data"
    with open(os.path.join(folder,"manifest.json"),encoding="utf-8") as f: manifest=json.load(f)
    if manifest.get("closed_candles_only") is not True: fail("Manifest does not certify closed candles")
    report={"requested_days":manifest.get("requested_days"),"candle_sets":{},"funding_sets":{},"common_ranges":{}}
    all_ranges={}
    for symbol in SYMBOLS:
        for market,inst in (("SPOT",symbol),("SWAP",symbol+"-SWAP")):
            for tf,step in TIMEFRAMES.items():
                key=f"{inst}:{tf}"
                meta=manifest.get("instruments",{}).get(key)
                if not meta: fail("Manifest missing "+key)
                stats=load_candles(os.path.join(folder,meta["file"]),step)
                if stats["candles"] != meta["candles"]: fail("Manifest candle count mismatch for "+key)
                report["candle_sets"][key]=stats
                all_ranges.setdefault(f"{market}:{tf}",[]).append((stats["first_ms"],stats["last_ms"]))
    for tf in TIMEFRAMES:
        for market in ("SPOT","SWAP"):
            ranges=all_ranges[f"{market}:{tf}"]
            report["common_ranges"][f"{market}:{tf}"]={
                "common_start_utc":datetime.fromtimestamp(max(x[0] for x in ranges)/1000,timezone.utc).isoformat(),
                "common_end_utc":datetime.fromtimestamp(min(x[1] for x in ranges)/1000,timezone.utc).isoformat()}
    with open(os.path.join(folder,"funding_manifest.json"),encoding="utf-8") as f: fm=json.load(f)
    for symbol in SYMBOLS:
        inst=symbol+"-SWAP"; meta=fm.get("instruments",{}).get(inst)
        if not meta: fail("Funding manifest missing "+inst)
        stats=load_funding(os.path.join(folder,meta["file"]))
        if stats["records"] != meta["records"]: fail("Funding manifest count mismatch for "+inst)
        report["funding_sets"][inst]=stats
    out=os.path.join(folder,"data_audit_report.json")
    with open(out,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({"status":"PASS","report":out,"candle_sets":len(report["candle_sets"]),
                      "funding_sets":len(report["funding_sets"]),"requested_days":report["requested_days"]},
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
