#!/usr/bin/env python3
"""Research-only MFI/OBV confirmation tests for OKX SPOT and USDT SWAP."""
import argparse, bisect, csv, json, math, os
from collections import defaultdict
from datetime import datetime, timezone

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
TIMEFRAMES = {"15m": 900000, "1H": 3600000, "4H": 14400000}
FEE_SIDE, SLIPPAGE_SIDE, STOP_ATR, TARGET_R = 0.0005, 0.0002, 1.5, 2.0
MAX_DAILY = 15
TRAIN_FRACTION = 2/3

def ema(values, period):
    out=[]; alpha=2.0/(period+1)
    for x in values: out.append(float(x) if not out else alpha*float(x)+(1-alpha)*out[-1])
    return out

def load_bars(path, market):
    out=[]
    with open(path,newline="",encoding="utf-8") as f:
        rd=csv.DictReader(f)
        required={"timestamp_ms","open","high","low","close","volume","volume_currency"}
        if not required.issubset(set(rd.fieldnames or [])): raise RuntimeError(f"{path}: missing required OHLCV columns")
        for r in rd:
            # OKX SPOT volume is base-asset volume; SWAP volume is contracts,
            # so use volume_currency (underlying base-asset units) for Futures.
            v=float(r["volume"] if market=="SPOT" else r["volume_currency"])
            o,h,l,c=[float(r[k]) for k in ("open","high","low","close")]
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or v<=0: raise RuntimeError(f"{path}: invalid/non-positive OHLCV")
            out.append({"ts":int(r["timestamp_ms"]),"o":o,"h":h,"l":l,"c":c,"v":v})
    out.sort(key=lambda x:x["ts"])
    if len(out)<120: raise RuntimeError(f"{path}: insufficient candles ({len(out)})")
    if len({x["ts"] for x in out})!=len(out): raise RuntimeError(f"{path}: duplicate timestamps")
    return out

def indicators(b):
    n=len(b); c=[x["c"] for x in b]; e50=ema(c,50); m=[a-z for a,z in zip(ema(c,12),ema(c,26))]; ms=ema(m,9)
    atr=[None]*n; rsi=[None]*n; mfi=[None]*n; obv=[0.0]*n
    for i in range(1,n):
        x,p=b[i],b[i-1]
        obv[i]=obv[i-1]+(x["v"] if x["c"]>p["c"] else (-x["v"] if x["c"]<p["c"] else 0))
        if i>=14:
            trs=[]; changes=[]; pos=neg=0.0
            for k in range(i-13,i+1):
                q,prev=b[k],b[k-1]
                trs.append(max(q["h"]-q["l"],abs(q["h"]-prev["c"]),abs(q["l"]-prev["c"])))
                changes.append(q["c"]-prev["c"])
                typ=(q["h"]+q["l"]+q["c"])/3; ptyp=(prev["h"]+prev["l"]+prev["c"])/3
                flow=typ*q["v"]
                if typ>ptyp: pos+=flow
                elif typ<ptyp: neg+=flow
            atr[i]=sum(trs)/14
            gain=sum(max(x,0) for x in changes)/14; loss=sum(max(-x,0) for x in changes)/14
            rsi[i]=100 if loss==0 and gain>0 else (50 if loss==0 else 100-100/(1+gain/loss))
            mfi[i]=100 if neg==0 and pos>0 else (50 if neg==0 else 100-100/(1+pos/neg))
    return {"ema50":e50,"macd":m,"macd_signal":ms,"atr":atr,"rsi":rsi,"mfi":mfi,"obv":obv,"obv_ema":ema(obv,20)}

def signals_for(b,ind,market):
    out=[]
    for i in range(len(b)-1):
        r,m,a=ind["rsi"][i],ind["mfi"][i],ind["atr"][i]
        direction=None
        if r is not None and m is not None and a and a>0:
            p=b[i]["c"]
            if p>ind["ema50"][i] and ind["macd"][i]>ind["macd_signal"][i] and 50<r<68: direction="LONG"
            elif market=="FUTURES" and p<ind["ema50"][i] and ind["macd"][i]<ind["macd_signal"][i] and 32<r<50: direction="SHORT"
        if direction:
            mfi_ok=(50<=m<=80) if direction=="LONG" else (20<=m<=50)
            obv_ok=(ind["obv"][i]>ind["obv_ema"][i]) if direction=="LONG" else (ind["obv"][i]<ind["obv_ema"][i])
            out.append({"direction":direction,"atr":a,"mfi_ok":mfi_ok,"obv_ok":obv_ok})
        else: out.append(None)
    return out

def funding_load(path):
    if not os.path.exists(path): return [],[]
    rows=[]
    with open(path,newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f): rows.append((int(r["funding_time_ms"]),float(r["rate"])))
    rows.sort()
    return [x[0] for x in rows],rows

def replay(b,sg,ft,fr,market,variant,tfms):
    trades=[]; daily=defaultdict(int); occupied_until=-1
    # One position at a time per symbol; signal at close, entry next candle open.
    for i,s in enumerate(sg):
        if s is None or i+1>=len(b) or i<occupied_until: continue
        if variant=="MFI" and not s["mfi_ok"]: continue
        if variant=="OBV" and not s["obv_ok"]: continue
        entrybar=b[i+1]; day=datetime.fromtimestamp((b[i]["ts"]+tfms)/1000,timezone.utc).date().isoformat()
        if daily[day]>=MAX_DAILY: continue
        entry=entrybar["o"]; d=1 if s["direction"]=="LONG" else -1; risk=s["atr"]*STOP_ATR
        if entry<=0 or risk<=0: continue
        stop=entry-d*risk; target=entry+d*risk*TARGET_R
        fs=bisect.bisect_right(ft,entrybar["ts"]); fsum=0.0; closed=False
        for j in range(i+1,len(b)):
            x=b[j]
            fe=bisect.bisect_right(ft,x["ts"])
            if market=="FUTURES" and fe>fs:
                fsum+=sum(z[1] for z in fr[fs:fe]); fs=fe
            sl=(x["l"]<=stop) if d==1 else (x["h"]>=stop)
            tp=(x["h"]>=target) if d==1 else (x["l"]<=target)
            if sl or tp:
                exitp=(min(x["o"],stop) if d==1 else max(x["o"],stop)) if sl else target
                gross=d*(exitp-entry)/entry; funding=d*fsum if market=="FUTURES" else 0
                net=gross-2*(FEE_SIDE+SLIPPAGE_SIDE)-funding
                trades.append({"variant":variant,"direction":s["direction"],"net_R":net/(risk/entry),"net_return_pct":net*100,"exit":"STOP" if sl else "TARGET"})
                occupied_until=j; closed=True; break
        if not closed:
            x=b[-1]; gross=d*(x["c"]-entry)/entry; funding=d*fsum if market=="FUTURES" else 0
            net=gross-2*(FEE_SIDE+SLIPPAGE_SIDE)-funding
            trades.append({"variant":variant,"direction":s["direction"],"net_R":net/(risk/entry),"net_return_pct":net*100,"exit":"OPEN_MARK_TO_CLOSE"})
            occupied_until=len(b)-1
        daily[day]+=1
    return trades

def summary(ts):
    closed=[x for x in ts if x["exit"]!="OPEN_MARK_TO_CLOSE"]; rs=[x["net_R"] for x in closed]
    wins=sum(x>0 for x in rs); losses=sum(x<0 for x in rs); gp=sum(x for x in rs if x>0); gl=-sum(x for x in rs if x<0)
    eq=peak=1.0; dd=0.0
    for r in rs:
        eq*=max(0,1+0.01*r); peak=max(peak,eq)
        if peak: dd=max(dd,(peak-eq)/peak)
    return {"trades_including_open_mark":len(ts),"closed_trades":len(closed),"open_at_end":len(ts)-len(closed),
        "wins":wins,"losses":losses,"win_rate_pct":round(100*wins/(wins+losses),2) if wins+losses else None,
        "net_R":round(sum(rs),3),"profit_factor":round(gp/gl,3) if gl else None,
        "approx_max_drawdown_pct_at_1pct_risk":round(dd*100,2)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data",default="research-data"); ap.add_argument("--out",default="mfi-obv-results"); a=ap.parse_args()
    rows=[]; trades=[]; quality={}
    for market in ("SPOT","FUTURES"):
        suf="" if market=="SPOT" else "_SWAP"
        for sym in SYMBOLS:
            base=sym.replace("-","_")
            ft,fr=([],[])
            if market=="FUTURES":
                ft,fr=funding_load(os.path.join(a.data,base+"_SWAP_funding.csv"))
                if not fr: raise RuntimeError(f"Missing Futures funding history: {sym}")
            for tf,tfms in TIMEFRAMES.items():
                path=os.path.join(a.data,f"{base}{suf}_{tf}.csv"); b=load_bars(path,market)
                sg=signals_for(b,indicators(b),market); candidates=sum(x is not None for x in sg)
                quality[f"{market}:{sym}:{tf}"]={"candles":len(b),"baseline_candidates":candidates,
                    "volume_column":"volume (base asset)" if market=="SPOT" else "volume_currency (underlying base asset)",
                    "funding_records":len(fr) if market=="FUTURES" else 0}
                split=int(len(b)*TRAIN_FRACTION)
                for segment,lo,hi in (("train",0,split),("validation",split,len(b))):
                    bb=b[lo:hi]; ss=sg[lo:hi]
                    for variant in ("BASELINE","MFI","OBV"):
                        tt=replay(bb,ss,ft,fr,market,variant,tfms)
                        rows.append({"market":market,"symbol":sym,"timeframe":tf,"segment":segment,"variant":variant,**summary(tt)})
                        trades.extend([{**t,"market":market,"symbol":sym,"timeframe":tf,"segment":segment} for t in tt])
                print(f"{market} {sym} {tf}: {len(b)} candles; {candidates} baseline candidates",flush=True)
    os.makedirs(a.out,exist_ok=True)
    with open(os.path.join(a.out,"summary.csv"),"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with open(os.path.join(a.out,"trades.csv"),"w",newline="",encoding="utf-8") as f:
        fields=["market","symbol","timeframe","segment","variant","direction","net_R","net_return_pct","exit"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(trades)
    with open(os.path.join(a.out,"data_quality.json"),"w",encoding="utf-8") as f:
        json.dump({"volume_semantics":"SPOT uses volume; SWAP uses volume_currency (base asset units)",
          "fees_per_side_pct":FEE_SIDE*100,"slippage_per_side_pct":SLIPPAGE_SIDE*100,
          "stop_atr":STOP_ATR,"target_R":TARGET_R,"max_new_entries_per_utc_day":MAX_DAILY,
          "chronological_train_fraction":TRAIN_FRACTION,"funding":"historical OKX funding applied to Futures only",
          "same_candle_rule":"stop assumed first","coverage":quality},f,indent=2)
    print(f"Completed: {len(rows)} summary rows; {len(trades)} trade records.",flush=True)

if __name__=="__main__": main()
