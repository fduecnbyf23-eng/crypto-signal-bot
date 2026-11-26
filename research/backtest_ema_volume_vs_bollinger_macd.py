#!/usr/bin/env python3
"""Compare EMA+RSI+volume and Bollinger+MACD on OKX USDT-SWAP. Research only."""
import argparse, json, os, statistics
from datetime import datetime, timezone
from collections import defaultdict
import backtest_strategy as bt

SYMBOLS = bt.SYMBOLS

def rsi(values, period=14):
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    if len(changes)<period: return 50.0
    gains=[max(x,0.0) for x in changes[-period:]]
    losses=[max(-x,0.0) for x in changes[-period:]]
    ag=sum(gains)/period; al=sum(losses)/period
    if al==0: return 100.0 if ag else 50.0
    return 100.0-100.0/(1.0+ag/al)

def make_signals(bars, strategy):
    closes=[b["c"] for b in bars]
    volumes=[b["v"] for b in bars]
    ema50=bt.ema(closes,50)
    fast=bt.ema(closes,12); slow=bt.ema(closes,26)
    macd=[fast[i]-slow[i] for i in range(len(bars))]
    macd_signal=bt.ema(macd,9)
    out={}
    for i in range(99,len(bars)-1):
        ind=bt.indicators(bars,i)
        if not ind: continue
        price=closes[i]; direction=None
        if strategy=="ema_rsi_volume":
            prev=volumes[max(0,i-20):i]
            if len(prev)<20: continue
            volume_ok=volumes[i] > statistics.mean(prev)*1.2
            strength=rsi(closes[max(0,i-30):i+1])
            if price>ema50[i] and 52.0<strength<68.0 and volume_ok: direction="LONG"
            elif price<ema50[i] and 32.0<strength<48.0 and volume_ok: direction="SHORT"
        elif strategy=="bollinger_macd":
            window=closes[i-19:i+1]
            mid=statistics.mean(window)
            sd=statistics.pstdev(window)
            upper=mid+2.0*sd; lower=mid-2.0*sd
            if price>upper and macd[i]>macd_signal[i]: direction="LONG"
            elif price<lower and macd[i]<macd_signal[i]: direction="SHORT"
        if direction:
            out[bars[i]["ts"]]={"direction":direction,"atr":ind["atr"]}
    return out

def make_data(folder, start, end, strategy):
    data={}; meta={}
    for symbol in SYMBOLS:
        base=symbol.replace("-","_")
        bars=bt.read_csv(os.path.join(folder,base+"_SWAP_15m.csv"))
        if not bars: raise RuntimeError("Missing SWAP candles for "+symbol)
        signals=make_signals(bars,strategy)
        funding=bt.load_funding(folder,symbol)
        data[symbol]={
            "bars":bars,"bar_map":{b["ts"]:b for b in bars},
            "next_bar":{bars[i]["ts"]:bars[i+1] for i in range(len(bars)-1)},
            "signals":signals,"funding":funding,
            "funding_times":[x[0] for x in funding],
        }
        meta[symbol]={"15m_bars":len(bars),"signal_candidates":len(signals),"funding_records":len(funding)}
    return data,meta

def run_window(data,start,end):
    subset={}
    for symbol,x in data.items():
        bars=[b for b in x["bars"] if start<=b["ts"]<end]
        keys={b["ts"] for b in bars}
        subset[symbol]={**x,"bars":bars,
            "bar_map":{k:x["bar_map"][k] for k in keys},
            "next_bar":{k:v for k,v in x["next_bar"].items() if k in keys and v["ts"]<end},
            "signals":{k:v for k,v in x["signals"].items() if k in keys}}
    trades=bt.simulate(subset,"baseline")
    return bt.summarize(trades),trades

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data",default="research-data")
    p.add_argument("--out",default="research-results")
    a=p.parse_args()
    # Restrict both strategies to the exact common overlap of all five SWAP datasets.
    allbars={}
    for symbol in SYMBOLS:
        allbars[symbol]=bt.read_csv(os.path.join(a.data,symbol.replace("-","_")+"_SWAP_15m.csv"))
        if len(allbars[symbol])<500: raise RuntimeError("Insufficient candle history for "+symbol)
    start=max(x[0]["ts"] for x in allbars.values())
    end=min(x[-1]["ts"] for x in allbars.values())
    if end<=start: raise RuntimeError("No common candle overlap")
    split=start+int((end-start)*0.70)
    variants=("ema_rsi_volume","bollinger_macd")
    results={}; metadata={}
    os.makedirs(a.out,exist_ok=True)
    for strategy in variants:
        data,meta=make_data(a.data,start,end,strategy)
        metadata[strategy]=meta
        train,train_trades=run_window(data,start,split)
        holdout,holdout_trades=run_window(data,split,end)
        results[strategy]={"train":train,"holdout":holdout}
        fields=["symbol","variant","direction","signal_time_utc","entry_time_utc","exit_time_utc","entry","exit","exit_reason","gross_return_pct","fees_and_slippage_pct","funding_cost_pct","net_return_pct","net_R","bars_held"]
        with open(os.path.join(a.out,strategy+"_holdout_trades.csv"),"w",newline="",encoding="utf-8") as f:
            import csv
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
            for t in holdout_trades:
                t["variant"]=strategy
                w.writerow(t)
    iso=lambda x:datetime.fromtimestamp(x/1000,timezone.utc).isoformat()
    report={
      "market":"OKX USDT perpetual SWAP",
      "common_start_utc":iso(start),"common_end_utc":iso(end),
      "train_end_utc":iso(split),"holdout_start_utc":iso(split),
      "method":"Identical common candle overlap for all five symbols; chronological 70/30 split; indicators calculated causally; signal on closed 15m candle, entry next 15m open; one open position per symbol; max 15 new entries per UTC day; stop 1.5 ATR, target 2R; stop assumed first if SL and TP hit in same candle.",
      "costs":"0.05% fee and 0.02% slippage per side (estimates), plus historical OKX funding where available. No parameter optimization.",
      "strategies":{
        "ema_rsi_volume":"LONG: close above EMA50, RSI(14) 52-68, volume > 1.2x mean of prior 20 candles. SHORT: close below EMA50, RSI 32-48, same volume rule.",
        "bollinger_macd":"LONG: close above upper 2-standard-deviation 20-candle Bollinger band and MACD(12,26) above signal(9). SHORT: close below lower band and MACD below signal."
      },
      "data":metadata,"results":results
    }
    with open(os.path.join(a.out,"ema_rsi_volume_vs_bollinger_macd.json"),"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    with open(os.path.join(a.out,"summary.md"),"w",encoding="utf-8") as f:
      f.write("# EMA/RSI/Volume vs Bollinger/MACD — research only\n\n")
      f.write(f"Common candles: {iso(start)} to {iso(end)} UTC. Holdout starts {iso(split)}.\n\n")
      f.write("Both strategies use identical SWAP candles, next-bar entries, ATR exits, daily cap, estimated costs and historical funding. No tuning.\n\n")
      f.write("| Strategy | Segment | Closed trades | Win rate | Net R | Avg R | Profit factor | Approx DD |\n|---|---|---:|---:|---:|---:|---:|---:|\n")
      for name in variants:
       for seg in ("train","holdout"):
        m=results[name][seg]; pf=m["profit_factor_R"]
        f.write(f"| {name} | {seg} | {m['closed_trades']} | {m['win_rate_pct']:.1f}% | {m['closed_net_R']:.2f} | {m['average_closed_net_R']:.3f} | {pf if pf is not None else 'n/a'} | {m['approx_max_drawdown_pct_at_1pct_risk']:.1f}% |\n")
      f.write("\nSimulation only; not actual fills or a guarantee of future performance. PF below 1 is unprofitable. Verify cost/funding coverage before interpretation.\n")
    print(json.dumps({"results":results,"common_start_utc":iso(start),"common_end_utc":iso(end),"holdout_start_utc":iso(split)},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
