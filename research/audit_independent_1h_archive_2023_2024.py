#!/usr/bin/env python3
"""Fail-closed audit for the frozen 2023-11-26 to 2024-11-25 1H archive."""
import csv, json, os
from datetime import datetime, timezone
START=int(datetime(2023,11,26,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2024,11,25,tzinfo=timezone.utc).timestamp()*1000)
HOUR=3600000
SYMBOLS=["BTC","ETH","SOL","BNB","XRP"]
def read(path):
    with open(path,newline="",encoding="utf-8") as f: return list(csv.DictReader(f))
def main():
    folder="independent-1h-data"
    report={"start_utc":datetime.fromtimestamp(START/1000,timezone.utc).isoformat(),"end_utc_exclusive":datetime.fromtimestamp(END/1000,timezone.utc).isoformat(),"candle_sets":{},"funding_sets":{},"all_valid":True}
    m=json.load(open(os.path.join(folder,"manifest.json"),encoding="utf-8"))
    if m.get("timeframe")!="1H" or len(m.get("instruments",{}))!=10: raise SystemExit("Unexpected candle manifest")
    for s in SYMBOLS:
      for sw in (False,True):
        inst=f"{s}-USDT-SWAP" if sw else f"{s}-USDT"
        fn=f"{s}_USDT{'_SWAP' if sw else ''}_1H.csv"; rows=read(os.path.join(folder,fn)); ts=[int(x["timestamp_ms"]) for x in rows]
        gaps=sum(1 for a,b in zip(ts,ts[1:]) if b-a!=HOUR)
        valid=len(rows)==8760 and ts[0]==START and ts[-1]==END-HOUR and len(set(ts))==8760 and gaps==0 and all(x["confirm"]=="1" for x in rows)
        report["candle_sets"][inst]={"candles":len(rows),"first":ts[0] if ts else None,"last":ts[-1] if ts else None,"gaps":gaps,"valid":valid}
        report["all_valid"] &= valid
    fm=json.load(open(os.path.join(folder,"funding_manifest.json"),encoding="utf-8"))
    if len(fm.get("instruments",{}))!=5: raise SystemExit("Unexpected funding manifest")
    for s in SYMBOLS:
      inst=f"{s}-USDT-SWAP"; rows=read(os.path.join(folder,f"{s}_USDT_SWAP_funding.csv")); ts=[int(x["funding_time_ms"]) for x in rows]
      expected=list(range(START,END,8*HOUR)); missing=sum(1 for t in expected if t not in set(ts))
      valid=len(rows)==1095 and ts[0]==START and ts[-1]==END-8*HOUR and len(set(ts))==1095 and missing==0
      report["funding_sets"][inst]={"records":len(rows),"missing":missing,"valid":valid}
      report["all_valid"] &= valid
    with open(os.path.join(folder,"independent_1h_audit_report.json"),"w",encoding="utf-8") as f: json.dump(report,f,indent=2)
    if not report["all_valid"]: raise SystemExit("Independent archive failed audit")
    print("INDEPENDENT_1H_AUDIT_OK 87600 candles 5475 funding rows",flush=True)
if __name__=="__main__": main()
