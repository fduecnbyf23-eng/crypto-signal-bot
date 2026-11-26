#!/usr/bin/env python3
"""Structural audit for the extended two-year daily candle archive."""
import csv,json,os,sys
from datetime import datetime,timezone

SYMBOLS=["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT","XRP-USDT"]
INSTRUMENTS=SYMBOLS+[x+"-SWAP" for x in SYMBOLS]

def main():
    folder=sys.argv[1] if len(sys.argv)>1 else "research-daily-2y"
    with open(os.path.join(folder,"manifest.json"),encoding="utf-8") as f: m=json.load(f)
    if m.get("closed_candles_only") is not True or m.get("timeframe")!="1Dutc":
        raise RuntimeError("Manifest does not describe closed 1Dutc candles")
    report={"requested_days":m.get("requested_days"),"datasets":{}}
    for inst in INSTRUMENTS:
        key=inst+":1Dutc"; meta=m.get("instruments",{}).get(key)
        if not meta: raise RuntimeError("Missing manifest entry "+key)
        path=os.path.join(folder,meta["file"])
        rows=[]
        with open(path,newline="",encoding="utf-8") as f:
            reader=csv.DictReader(f)
            required={"timestamp_ms","open","high","low","close","volume_quote","confirm"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise RuntimeError("Missing columns "+path)
            for r in reader:
                ts=int(r["timestamp_ms"]); o,h,l,c=[float(r[k]) for k in ("open","high","low","close")]
                if r["confirm"]!="1" or min(o,h,l,c)<=0 or h<max(o,c,l) or l>min(o,c,h) or float(r["volume_quote"])<0:
                    raise RuntimeError("Invalid/unclosed candle "+path)
                rows.append(ts)
        if len(rows)<600 or rows!=sorted(set(rows)):
            raise RuntimeError("Insufficient, duplicate or unordered daily candles "+path)
        gaps=sum(1 for a,b in zip(rows,rows[1:]) if b-a!=86400000)
        if len(rows)!=meta["candles"]:
            raise RuntimeError("Manifest count mismatch "+path)
        report["datasets"][inst]={
            "candles":len(rows),
            "first_utc":datetime.fromtimestamp(rows[0]/1000,timezone.utc).isoformat(),
            "last_utc":datetime.fromtimestamp(rows[-1]/1000,timezone.utc).isoformat(),
            "interval_gaps":gaps}
    starts=[v["first_utc"] for v in report["datasets"].values()]
    ends=[v["last_utc"] for v in report["datasets"].values()]
    report["common_start_utc"]=max(starts)
    report["common_end_utc"]=min(ends)
    out=os.path.join(folder,"daily_2y_audit_report.json")
    with open(out,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({"status":"PASS","datasets":len(report["datasets"]),
                      "total_candles":sum(v["candles"] for v in report["datasets"].values()),
                      "common_start_utc":report["common_start_utc"],
                      "common_end_utc":report["common_end_utc"]},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
