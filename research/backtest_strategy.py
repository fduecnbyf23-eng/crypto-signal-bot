#!/usr/bin/env python3
"""Candle-close-only OKX USDT swap replay. Research only; never places orders."""
import argparse, bisect, csv, json, os, statistics
from collections import defaultdict
from datetime import datetime, timezone

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
FEE_SIDE = 0.0005       # placeholder: 5 bps per fill
SLIPPAGE_SIDE = 0.0002  # placeholder: 2 bps per fill

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{"ts":int(r["timestamp_ms"]),"o":float(r["open"]),"h":float(r["high"]),"l":float(r["low"]),"c":float(r["close"]),"v":float(r["volume"])} for r in csv.DictReader(f)]

def ema(values, period):
    if not values: return []
    a=2.0/(period+1.0); out=[values[0]]
    for x in values[1:]: out.append(x*a+out[-1]*(1-a))
    return out

def indicators(bars, i):
    w=bars[max(0,i-99):i+1]; c=[x["c"] for x in w]
    if len(c)<60: return None
    e50=ema(c,50)[-1]
    changes=[c[k]-c[k-1] for k in range(1,len(c))]
    gains=[max(x,0.0) for x in changes[-14:]]; losses=[max(-x,0.0) for x in changes[-14:]]
    ag=sum(gains)/14; al=sum(losses)/14
    rsi=100.0 if al==0 and ag>0 else (50.0 if al==0 else (0.0 if ag==0 else 100.0-100.0/(1.0+ag/al)))
    fast=ema(c,12); slow=ema(c,26); macds=[fast[j]-slow[j] for j in range(25,len(c))]
    macd=macds[-1]; sig=ema(macds[-9:],9)[-1]
    tr=[]
    for k in range(1,len(w)):
        b=w[k]; pc=w[k-1]["c"]; tr.append(max(b["h"]-b["l"],abs(b["h"]-pc),abs(b["l"]-pc)))
    atr=sum(tr[-14:])/14
    return {"ema50":e50,"rsi":rsi,"macd":macd,"signal":sig,"atr":atr,"atr_pct":atr/c[-1]}

def adx_series(bars, period=14):
    out=[None]*len(bars); tr=[]; pdm=[]; mdm=[]
    for i in range(1,len(bars)):
        c,p=bars[i],bars[i-1]; up=c["h"]-p["h"]; down=p["l"]-c["l"]
        pdm.append(up if up>down and up>0 else 0.0); mdm.append(down if down>up and down>0 else 0.0)
        tr.append(max(c["h"]-c["l"],abs(c["h"]-p["c"]),abs(c["l"]-p["c"])))
    if len(tr)<period*2: return out
    st=sum(tr[:period]); sp=sum(pdm[:period]); sm=sum(mdm[:period]); dx=[]
    for j in range(period-1,len(tr)):
        if j>period-1:
            st=st-st/period+tr[j]; sp=sp-sp/period+pdm[j]; sm=sm-sm/period+mdm[j]
        pdi=100*sp/st if st else 0; mdi=100*sm/st if st else 0; den=pdi+mdi
        dx.append(100*abs(pdi-mdi)/den if den else 0)
        idx=j+1
        if len(dx)==period: out[idx]=sum(dx)/period
        elif len(dx)>period and out[idx-1] is not None: out[idx]=(out[idx-1]*(period-1)+dx[-1])/period
    return out

def higher_lookup(bars, duration):
    return [b["ts"]+duration for b in bars], ema([b["c"] for b in bars],50)

def load_funding(folder,symbol):
    path=os.path.join(folder,symbol.replace("-","_")+"_SWAP_funding.csv"); out=[]
    if os.path.exists(path):
        with open(path,newline="",encoding="utf-8") as f:
            for r in csv.DictReader(f): out.append((int(r["funding_time_ms"]),float(r["rate"])))
    return sorted(out)

def make_signal(bars,i,ind,adx,h1,h4,e1,e4,c1,c4,atr_hist):
    price=bars[i]["c"]; direction=None
    if price>ind["ema50"] and ind["macd"]>ind["signal"] and 50<ind["rsi"]<68: direction="LONG"
    elif price<ind["ema50"] and ind["macd"]<ind["signal"] and 32<ind["rsi"]<50: direction="SHORT"
    if not direction: return None
    close_ts=bars[i]["ts"]+900000; j1=bisect.bisect_right(c1,close_ts)-1; j4=bisect.bisect_right(c4,close_ts)-1
    mtf=False
    if j1>=0 and j4>=0:
        mtf=(h1[j1]["c"]>e1[j1] and h4[j4]["c"]>e4[j4]) if direction=="LONG" else (h1[j1]["c"]<e1[j1] and h4[j4]["c"]<e4[j4])
    adx_ok=adx[i] is not None and adx[i]>=18.0
    pv=[x["v"] for x in bars[max(0,i-20):i]]
    volume_ok=len(pv)==20 and bars[i]["v"]>sum(pv)/20*1.2
    prev=bars[max(0,i-20):i]
    if len(prev)==20:
        resistance=max(x["h"] for x in prev); support=min(x["l"] for x in prev)
        sr_ok=(resistance-price)>0.5*ind["atr"] if direction=="LONG" else (price-support)>0.5*ind["atr"]
    else: sr_ok=False
    prior=sorted(atr_hist[-96:]); med=statistics.median(prior) if len(prior)>=48 else None
    vol_ok=med is not None and 0.5*med<=ind["atr_pct"]<=2.0*med
    return {"direction":direction,"atr":ind["atr"],"mtf":mtf,"adx":adx_ok,"volume":volume_ok,"sr":sr_ok,"volatility":vol_ok}

def simulate(data,variant):
    timeline=sorted({ts for x in data.values() for ts in x["bar_map"]}); positions={}; trades=[]; daily=defaultdict(int)
    for ts in timeline:
        exited=set()
        for symbol in SYMBOLS:
            x=data[symbol]; b=x["bar_map"].get(ts); p=positions.get(symbol)
            if b is None or p is None or ts<p["entry_ts"]: continue
            hi=bisect.bisect_right(x["funding_times"],ts)
            if hi>p["funding_cursor"]:
                p["funding_sum"]+=sum(r for _,r in x["funding"][p["funding_cursor"]:hi]); p["funding_cursor"]=hi
            sl=(b["l"]<=p["stop"] if p["dir"]=="LONG" else b["h"]>=p["stop"])
            tp=(b["h"]>=p["target"] if p["dir"]=="LONG" else b["l"]<=p["target"])
            if sl or tp:
                if sl:
                    exitp=min(b["o"],p["stop"]) if p["dir"]=="LONG" else max(b["o"],p["stop"])
                    reason="STOP_AND_TARGET_SAME_CANDLE_STOP_ASSUMED" if tp else "STOP"
                else: exitp=p["target"]; reason="TARGET"
                d=1 if p["dir"]=="LONG" else -1; gross=d*(exitp-p["entry"])/p["entry"]
                costs=2*(FEE_SIDE+SLIPPAGE_SIDE); fcost=d*p["funding_sum"]; net=gross-costs-fcost; risk=p["risk"]/p["entry"]
                trades.append({"symbol":symbol,"variant":variant,"direction":p["dir"],"signal_time_utc":p["signal_time"],"entry_time_utc":datetime.fromtimestamp(p["entry_ts"]/1000,timezone.utc).isoformat(),"exit_time_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),"entry":p["entry"],"exit":exitp,"exit_reason":reason,"gross_return_pct":gross*100,"fees_and_slippage_pct":costs*100,"funding_cost_pct":fcost*100,"net_return_pct":net*100,"net_R":net/risk if risk else 0,"bars_held":(ts-p["entry_ts"])//900000+1})
                del positions[symbol]; exited.add(symbol)
        day=datetime.fromtimestamp((ts+900000)/1000,timezone.utc).date().isoformat()
        for symbol in SYMBOLS:
            x=data[symbol]
            if symbol in positions or symbol in exited: continue
            s=x["signals"].get(ts)
            if s is None: continue
            if variant=="all_filters":
                if not all(s[k] for k in ("mtf","adx","volume","sr","volatility")): continue
            elif variant!="baseline" and not s[variant]: continue
            if daily[day]>=15: continue
            nxt=x["next_bar"].get(ts)
            if nxt is None: continue
            risk=s["atr"]*1.5; entry=nxt["o"]
            if risk<=0 or entry<=0: continue
            cur=bisect.bisect_right(x["funding_times"],nxt["ts"])
            positions[symbol]={"dir":s["direction"],"entry_ts":nxt["ts"],"entry":entry,"stop":entry-risk if s["direction"]=="LONG" else entry+risk,"target":entry+2*risk if s["direction"]=="LONG" else entry-2*risk,"risk":risk,"signal_time":datetime.fromtimestamp((ts+900000)/1000,timezone.utc).isoformat(),"funding_sum":0.0,"funding_cursor":cur}
            daily[day]+=1
    for symbol,p in positions.items():
        x=data[symbol]; b=x["bars"][-1]; hi=bisect.bisect_right(x["funding_times"],b["ts"])
        if hi>p["funding_cursor"]: p["funding_sum"]+=sum(r for _,r in x["funding"][p["funding_cursor"]:hi])
        d=1 if p["dir"]=="LONG" else -1; gross=d*(b["c"]-p["entry"])/p["entry"]; costs=2*(FEE_SIDE+SLIPPAGE_SIDE); fcost=d*p["funding_sum"]; net=gross-costs-fcost; risk=p["risk"]/p["entry"]
        trades.append({"symbol":symbol,"variant":variant,"direction":p["dir"],"signal_time_utc":p["signal_time"],"entry_time_utc":datetime.fromtimestamp(p["entry_ts"]/1000,timezone.utc).isoformat(),"exit_time_utc":datetime.fromtimestamp(b["ts"]/1000,timezone.utc).isoformat(),"entry":p["entry"],"exit":b["c"],"exit_reason":"OPEN_AT_END_MARK_TO_CLOSE","gross_return_pct":gross*100,"fees_and_slippage_pct":costs*100,"funding_cost_pct":fcost*100,"net_return_pct":net*100,"net_R":net/risk if risk else 0,"bars_held":max(0,(b["ts"]-p["entry_ts"])//900000+1)})
    return trades

def summarize(ts):
    closed=[t for t in ts if t["exit_reason"]!="OPEN_AT_END_MARK_TO_CLOSE"]; rs=[t["net_R"] for t in closed]
    wins=sum(r>0 for r in rs); losses=sum(r<0 for r in rs); eq=peak=1.0; dd=0.0
    for r in rs:
        eq*=max(0,1+0.01*r); peak=max(peak,eq); dd=max(dd,(peak-eq)/peak if peak else 0)
    gp=sum(r for r in rs if r>0); gl=-sum(r for r in rs if r<0)
    return {"trades_including_open_marks":len(ts),"closed_trades":len(closed),"open_at_end":len(ts)-len(closed),"wins_net":wins,"losses_net":losses,"win_rate_pct":100*wins/(wins+losses) if wins+losses else 0,"closed_net_R":sum(rs),"average_closed_net_R":statistics.mean(rs) if rs else 0,"profit_factor_R":gp/gl if gl else None,"approx_max_drawdown_pct_at_1pct_risk":dd*100,"long_trades":sum(t["direction"]=="LONG" for t in ts),"short_trades":sum(t["direction"]=="SHORT" for t in ts)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",default="research-data"); ap.add_argument("--out",default="research-results"); a=ap.parse_args()
    variants=["baseline","mtf","adx","volume","sr","volatility","all_filters"]; data={}; meta={}
    for symbol in SYMBOLS:
        base=symbol.replace("-","_"); bars=read_csv(os.path.join(a.data,base+"_15m.csv")); h1=read_csv(os.path.join(a.data,base+"_1H.csv")); h4=read_csv(os.path.join(a.data,base+"_4H.csv"))
        c1,e1=higher_lookup(h1,3600000); c4,e4=higher_lookup(h4,14400000); adx=adx_series(bars); hist=[]; signals={}
        for i in range(99,len(bars)-1):
            ind=indicators(bars,i)
            if ind:
                s=make_signal(bars,i,ind,adx,h1,h4,e1,e4,c1,c4,hist); hist.append(ind["atr_pct"])
                if s: signals[bars[i]["ts"]]=s
        funding=load_funding(a.data,symbol); bm={b["ts"]:b for b in bars}; nxt={bars[i]["ts"]:bars[i+1] for i in range(len(bars)-1)}
        data[symbol]={"bars":bars,"bar_map":bm,"next_bar":nxt,"signals":signals,"funding":funding,"funding_times":[r[0] for r in funding]}
        meta[symbol]={"15m_bars":len(bars),"1h_bars":len(h1),"4h_bars":len(h4),"funding_records":len(funding),"baseline_signal_candidates_before_daily_cap":len(signals)}
        print(f"{symbol}: {len(bars)} 15m candles, {len(signals)} candidates, {len(funding)} funding records",flush=True)
    os.makedirs(a.out,exist_ok=True); alltr=[]; summary={}; per_symbol={}; per_direction={}
    for v in variants:
        tr=simulate(data,v); alltr.extend(tr); summary[v]=summarize(tr)
        per_symbol[v]={s:summarize([t for t in tr if t["symbol"]==s]) for s in SYMBOLS}
        per_direction[v]={d:summarize([t for t in tr if t["direction"]==d]) for d in ("LONG","SHORT")}
    report={"market":"OKX USDT perpetual swap candles","method":"closed 15m signal, next 15m open entry; max one open position per symbol; 15 new entries per UTC day across portfolio; stop assumed first if SL and TP hit in same candle","fee_per_side_pct":FEE_SIDE*100,"slippage_per_side_pct":SLIPPAGE_SIDE*100,"cost_assumption":"placeholder 0.05% fee and 0.02% slippage per side; actual account rates and fills may differ","funding_note":"Uses OKX historical realizedRate when present, otherwise fundingRate; funding is applied at settlement timestamps while position is open. Verify record coverage.","data":meta,"summary":summary,"per_symbol_summary":per_symbol,"per_direction_summary":per_direction}
    with open(os.path.join(a.out,"backtest_summary.json"),"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    fields=["symbol","variant","direction","signal_time_utc","entry_time_utc","exit_time_utc","entry","exit","exit_reason","gross_return_pct","fees_and_slippage_pct","funding_cost_pct","net_return_pct","net_R","bars_held"]
    with open(os.path.join(a.out,"trades.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(alltr)
    with open(os.path.join(a.out,"summary.md"),"w",encoding="utf-8") as f:
        f.write("# Historical strategy replay (research only)\n\n")
        f.write("Simulation, not actual fills or future-performance guarantee. One open position per symbol; 15 new entries per UTC day; next 15m open entry; stop-first for same-candle SL/TP.\n\n")
        f.write("Assumptions: 0.05% fee and 0.02% slippage per side. Funding from OKX history where available.\n\n")
        f.write("| Variant | Trades | Win rate | Net R | Avg R | Profit factor | Approx. DD* |\n|---|---:|---:|---:|---:|---:|---:|\n")
        for v,m in summary.items(): f.write(f"| {v} | {m['trades_including_open_marks']} | {m['win_rate_pct']:.1f}% | {m['closed_net_R']:.2f} | {m['average_closed_net_R']:.3f} | {m['profit_factor_R'] if m['profit_factor_R'] is not None else 'n/a'} | {m['approx_max_drawdown_pct_at_1pct_risk']:.2f}% |\n")
        f.write("\n*Approximate compounded-R drawdown at 1% risk per trade; portfolio margin and correlated exposure are not modeled. Inspect funding coverage and assumptions before interpreting.\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
