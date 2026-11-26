#!/usr/bin/env python3
"""Download two years of closed daily OKX spot and SWAP candles only."""
import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone

from download_okx_candles import SPOT, SWAPS, download

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--days",type=int,default=730)
    parser.add_argument("--out",default="research-daily-2y")
    args=parser.parse_args()
    if not 366 <= args.days <= 800:
        parser.error("--days must be between 366 and 800")
    os.makedirs(args.out,exist_ok=True)
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=args.days)
    cutoff_ms=int(start.timestamp()*1000)
    manifest={
        "source":"OKX public market history-candles API",
        "downloaded_at_utc":end.isoformat(),
        "requested_days":args.days,
        "start_utc":start.isoformat(),
        "end_utc":end.isoformat(),
        "timeframe":"1Dutc",
        "closed_candles_only":True,
        "instruments":{},
        "note":"Daily candles only; research data, no credentials or order endpoints."
    }
    jobs=[(x,"SPOT") for x in SPOT]+[(x,"SWAP") for x in SWAPS]
    for n,(inst,market) in enumerate(jobs,1):
        print(f"[{n}/{len(jobs)}] {market} {inst} 1Dutc",flush=True)
        candles,pages=download(inst,"1Dutc",cutoff_ms)
        path=os.path.join(args.out,f"{inst.replace('-','_')}_1Dutc.csv")
        with open(path,"w",newline="",encoding="utf-8") as f:
            w=csv.writer(f)
            w.writerow(["timestamp_ms","utc_time","open","high","low","close",
                        "volume","volume_currency","volume_quote","confirm"])
            for row in candles:
                ts=int(row[0])
                w.writerow([ts,datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                            *row[1:8],row[8]])
        manifest["instruments"][f"{inst}:1Dutc"]={
            "market":market,"file":os.path.basename(path),"candles":len(candles),
            "pages":pages,"first_timestamp_ms":int(candles[0][0]) if candles else None,
            "last_timestamp_ms":int(candles[-1][0]) if candles else None}
        print(f"  saved {len(candles)} closed daily candles ({pages} pages)",flush=True)
    with open(os.path.join(args.out,"manifest.json"),"w",encoding="utf-8") as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    total=sum(x["candles"] for x in manifest["instruments"].values())
    print(f"Completed {total} daily candles across {len(jobs)} instruments.",flush=True)

if __name__=="__main__":
    main()
