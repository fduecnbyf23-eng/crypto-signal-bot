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
    rates={}
    add_archive_rates("ETH-USDT-SWAP",START,END,rates)
    stamps=sorted(rates)
    expected=set(range(START,END,8*HOUR))
    actual=set(stamps)
    missing=sorted(expected-actual)
    extra=sorted(actual-expected)
    deltas=[b-a for a,b in zip(stamps,stamps[1:])]
    from collections import Counter
    interval_counts=Counter(round(x/HOUR,3) for x in deltas)
    offset_counts=Counter(((x-START)%(8*HOUR))//(60*1000) for x in stamps)
    os.makedirs("funding-diagnostic",exist_ok=True)
    with open("funding-diagnostic/eth_funding_timestamps.csv","w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["funding_time_ms","utc_time","rate"])
        for ts in stamps: w.writerow([ts,iso(ts),rates[ts]["rate"]])
    report={
      "instrument":"ETH-USDT-SWAP","start_utc":iso(START),"end_utc_exclusive":iso(END),
      "record_count":len(stamps),"unique_count":len(actual),
      "missing_from_midnight_utc_8h_grid":len(missing),"off_grid_count":len(extra),
      "first_timestamps":[iso(x) for x in stamps[:12]],
      "last_timestamps":[iso(x) for x in stamps[-12:]],
      "first_missing_expected":[iso(x) for x in missing[:20]],
      "first_off_grid_actual":[iso(x) for x in extra[:20]],
      "interval_hours_distribution":dict(sorted(interval_counts.items())),
      "offset_minutes_from_utc_00_08_16_grid_distribution":dict(sorted(offset_counts.items()))
    }
    with open("funding-diagnostic/eth_funding_diagnostic.json","w",encoding="utf-8") as f: json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2),flush=True)
if __name__=="__main__": main()
