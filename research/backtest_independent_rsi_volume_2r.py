#!/usr/bin/env python3
"""Frozen independent RSI+volume SHORT 1H SWAP replay with fixed 2R target."""
import argparse, csv, json, os
from indicator_features import build_features, apply_timeframe_scope
from backtest_frozen_indicators import read_csv, write_csv, funding_map, simulate, summarize
SYMBOLS=["BTC","ETH","SOL","BNB","XRP"]
START=1700956800000  # 2023-11-26T00:00:00Z
def main():
 p=argparse.ArgumentParser(); p.add_argument("--input-dir",default="independent-1h-data"); p.add_argument("--output-dir",default="independent-rsi-volume-2r"); a=p.parse_args()
 all_trades=[]; summaries=[]
 for s in SYMBOLS:
  cp=os.path.join(a.input_dir,f"{s}_USDT_SWAP_1H.csv"); fp=os.path.join(a.input_dir,f"{s}_USDT_SWAP_funding.csv")
  rows=read_csv(cp); stamps=[int(r["timestamp_ms"]) for r in rows]
  if len(rows)!=8760 or stamps[0]!=START or stamps[-1]!=START+8759*3600000 or any(y-x!=3600000 for x,y in zip(stamps,stamps[1:])): raise ValueError(f"{s}: candle coverage invalid")
  fmap,first,last,contiguous=funding_map(fp)
  if len(fmap)!=1095 or not contiguous: raise ValueError(f"{s}: funding coverage invalid ({len(fmap)})")
  feats=apply_timeframe_scope(build_features(rows),"1H")
  trades,invalid=simulate(rows,feats,"1H","never_true","rsi_volume_short","SWAP",s,"rsi_volume_short","base","independent_2023_2024",None,None,fmap,first,contiguous)
  all_trades.extend(trades)
  summaries.append({"aggregation_level":"SYMBOL","market":"SWAP","symbol":s,"timeframe":"1H","direction":"SHORT","strategy":"rsi_volume_short","exit_mode":"base_2R","period":"independent_2023_2024","candles":len(rows),"funding_records":len(fmap),"funding_first_utc":first,"funding_last_utc":last,**summarize(trades,invalid)})
 all_trades.sort(key=lambda t:(t["exit_time_utc"] or "9999",t["entry_time_utc"]))
 invalid=sum(1 for t in all_trades if t["funding_valid"] is False)
 summaries.append({"aggregation_level":"ALL_SYMBOLS","market":"SWAP","symbol":"ALL","timeframe":"1H","direction":"SHORT","strategy":"rsi_volume_short","exit_mode":"base_2R","period":"independent_2023_2024",**summarize(all_trades,invalid)})
 os.makedirs(a.output_dir,exist_ok=True); write_csv(os.path.join(a.output_dir,"trades.csv"),all_trades); write_csv(os.path.join(a.output_dir,"summary.csv"),summaries)
 meta={"candidate_id":"OKX_SWAP_RSI_VOLUME_SHORT_1H_BASE_2R_ALL5","window_start_utc_inclusive":"2023-11-26T00:00:00Z","window_end_utc_exclusive":"2024-11-25T00:00:00Z","symbols":SYMBOLS,"market":"OKX USDT-SWAP","timeframe":"1H","signal":"(RSI14 cross down through 70 OR confirmed bearish RSI divergence) AND quote_volume >= 1.5 * SMA20 quote_volume","entry":"next 1H candle open","exit":"1.5 ATR14 protective stop or fixed 2R target; stop-first if both touched in same candle","costs_per_side":{"taker_fee_pct":0.05,"slippage_pct":0.02},"funding":"historical OKX funding; positive funding received by SHORT","parameters_frozen":True,"no_orders_generated":True}
 with open(os.path.join(a.output_dir,"metadata.json"),"w") as f: json.dump(meta,f,indent=2)
 print(f"INDEPENDENT_RSI_VOLUME_2R_COMPLETE closed={sum(1 for t in all_trades if t['closed'])} open={sum(1 for t in all_trades if not t['closed'])} invalid_funding={invalid}",flush=True)
if __name__=="__main__":main()
