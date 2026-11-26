#!/usr/bin/env python3
"""Diagnostic only: inspect actual ETH-USDT-SWAP funding timestamps for 2023-11-26..2024-11-25."""
import csv, json, os
from datetime import datetime, timezone
from download_okx_funding_archive import add_archive_rates

START=int(datetime(2023,11,26,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2024,11,25,tzinfo=timezone.utc).timestamp()*1000)
HOUR=3600000
def iso(ts):
    return datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()

def main():
    from collections import Counter
    os.makedirs("funding-diagnostic",exist_ok=True)
    all_reports={}
    for inst in ["BTC-USDT-SWAP","ETH-USDT-SWAP","SOL-USDT-SWAP","BNB-USDT-SWAP","XRP-USDT-SWAP"]:
        rates={}
        add_archive_rates(inst,START,END,rates)
        stamps=sorted(rates)
        expected=list(range(START,END,8*HOUR))
        deltas=[b-a for a,b in zip(stamps,stamps[1:])]
        offsets=[ts-expected[min(range(len(expected)),key=lambda i:abs(expected[i]-ts))] for ts in stamps] if stamps else []
        interval_counts=Counter(round(x/1000,3) for x in deltas)
        nearest_offsets=Counter(x for x in offsets)
        report={
          "instrument":inst,"start_utc":iso(START),"end_utc_exclusive":iso(END),
          "record_count":len(stamps),"unique_count":len(set(stamps)),
          "count_within_5_seconds_of_expected_grid":sum(abs(x)<=5000 for x in offsets),
          "count_outside_5_seconds_of_expected_grid":sum(abs(x)>5000 for x in offsets),
          "first_timestamps":[iso(x) for x in stamps[:6]],
          "last_timestamps":[iso(x) for x in stamps[-6:]],
          "offset_ms_distribution":dict(sorted(nearest_offsets.items())),
          "interval_seconds_distribution":dict(sorted(interval_counts.items()))
        }
        all_reports[inst]=report
        safe=inst.replace("-","_")
        with open(f"funding-diagnostic/{safe}_funding_timestamps.csv","w",newline="",encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["funding_time_ms","utc_time","rate"])
            for ts in stamps: w.writerow([ts,iso(ts),rates[ts]["rate"]])
    with open("funding-diagnostic/funding_timestamp_diagnostic_all5.json","w",encoding="utf-8") as f: json.dump(all_reports,f,indent=2)
    print(json.dumps(all_reports,indent=2),flush=True)
if __name__=="__main__": main()
