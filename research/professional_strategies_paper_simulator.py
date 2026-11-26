#!/usr/bin/env python3
"""Paper-only tracker for Donchian, Turtle-style and Holy Grail-style systems.
No private credentials, exchange order endpoints, or Telegram access.
"""
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE="https://www.okx.com"
SYMBOLS=["BTC-USDT-SWAP","ETH-USDT-SWAP","SOL-USDT-SWAP","BNB-USDT-SWAP","XRP-USDT-SWAP"]
TFS={"1H":3600000,"4H":14400000}
START_BALANCE=1000.0
ORDER_USDT=10.0
FEE=0.0005
SLIP=0.0002
STATE="research/professional_paper_state.json"
REPORT="research/professional_paper_report.json"
REGISTRY="research/professional_paper_registry.json"

def now():
    return datetime.now(timezone.utc).isoformat()

def api(path, params):
    url=BASE+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":"CryptoSignalAI-Professional-Paper/1.0"})
    with urllib.request.urlopen(req,timeout=30) as resp:
        data=json.loads(resp.read().decode("utf-8"))
    if data.get("code")!="0":
        raise RuntimeError(f"OKX API error {data.get('code')}: {data.get('msg')}")
    return data.get("data",[])

def save(path,obj):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,indent=2); f.write("\n")
    os.replace(tmp,path)

def ema(v,p):
    out=[None]*len(v)
    if len(v)<p:return out
    x=sum(v[:p])/p; out[p-1]=x; a=2/(p+1)
    for i in range(p,len(v)):
        x=a*v[i]+(1-a)*x; out[i]=x
    return out

def wilder(v,p):
    out=[None]*len(v)
    if len(v)<=p:return out
    x=sum(v[1:p+1])/p; out[p]=x
    for i in range(p+1,len(v)):
        x=(x*(p-1)+v[i])/p; out[i]=x
    return out

def features(candles):
    o=[float(x[1]) for x in candles]; h=[float(x[2]) for x in candles]
    l=[float(x[3]) for x in candles]; c=[float(x[4]) for x in candles]
    tr=[0.0]; plus=[0.0]; minus=[0.0]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        up=h[i]-h[i-1]; dn=l[i-1]-l[i]
        plus.append(max(up,0.0) if up>dn else 0.0)
        minus.append(max(dn,0.0) if dn>up else 0.0)
    atr=wilder(tr,20)
    pdi=[None]*len(c); mdi=[None]*len(c); dx=[None]*len(c)
    smp=wilder(plus,14); smm=wilder(minus,14); smtr=wilder(tr,14)
    for i in range(len(c)):
        if smp[i] is not None and smm[i] is not None and smtr[i] not in (None,0):
            pdi[i]=100*smp[i]/smtr[i]; mdi[i]=100*smm[i]/smtr[i]
            den=pdi[i]+mdi[i]
            dx[i]=100*abs(pdi[i]-mdi[i])/den if den else 0.0
    adx=[None]*len(c)
    valid_dx=[x for x in dx if x is not None]
    first_dx=next((i for i,x in enumerate(dx) if x is not None),None)
    if first_dx is not None and len(valid_dx)>=14:
        seed_idx=first_dx+13
        value=sum(valid_dx[:14])/14
        adx[seed_idx]=value
        for j in range(seed_idx+1,len(c)):
            if dx[j] is not None:
                value=(value*13+dx[j])/14
                adx[j]=value
    return {"o":o,"h":h,"l":l,"c":c,"atr20":atr,"adx14":adx,
            "ema20":ema(c,20),"ema50":ema(c,50),"ema200":ema(c,200)}

def max_prior(arr,i,n):
    if i<n:return None
    return max(arr[i-n:i])

def min_prior(arr,i,n):
    if i<n:return None
    return min(arr[i-n:i])

def make_ids():
    return [f"{kind}_{sym.split('-')[0]}_{tf}"
            for kind in ("DONCHIAN_ENSEMBLE","TURTLE_STYLE","HOLY_GRAIL")
            for sym in SYMBOLS for tf in TFS]

def fresh_state():
    return {"version":1,"created_utc":now(),"mode":"PAPER_ONLY_NO_ORDERS",
            "accounts":{sid:{"starting_balance_usdt":START_BALANCE,"balance_usdt":START_BALANCE,
            "realized_pnl_usdt":0.0,"last_processed_candle":None,"position":None,
            "pending_signal":None,"trades":[]} for sid in make_ids()}}

def direction_signal(kind,f,i):
    c,h,l=f["c"],f["h"],f["l"]
    atr,adx=f["atr20"][i],f["adx14"][i]
    e20,e50,e200=f["ema20"][i],f["ema50"][i],f["ema200"][i]
    if atr is None or atr<=0:return None
    if kind in ("DONCHIAN_ENSEMBLE","TURTLE_STYLE"):
        b20h=max_prior(h,i,20); b20l=min_prior(l,i,20)
        b55h=max_prior(h,i,55); b55l=min_prior(l,i,55)
        if None in (b20h,b20l,b55h,b55l):return None
        long55=c[i]>b55h; short55=c[i]<b55l
        long20=c[i]>b20h; short20=c[i]<b20l
        if kind=="DONCHIAN_ENSEMBLE":
            if adx is None or adx<20 or e200 is None:return None
            if long55 and c[i]>e200:return {"direction":"LONG","entry_period":55,"exit_period":20,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if short55 and c[i]<e200:return {"direction":"SHORT","entry_period":55,"exit_period":20,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if long20 and c[i]>e200:return {"direction":"LONG","entry_period":20,"exit_period":10,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if short20 and c[i]<e200:return {"direction":"SHORT","entry_period":20,"exit_period":10,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
        else:
            if long55:return {"direction":"LONG","entry_period":55,"exit_period":20,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if short55:return {"direction":"SHORT","entry_period":55,"exit_period":20,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if long20:return {"direction":"LONG","entry_period":20,"exit_period":10,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
            if short20:return {"direction":"SHORT","entry_period":20,"exit_period":10,"atr":atr,"signal_close":c[i],"stop_atr":2.0}
        return None
    # Mechanical Holy Grail-style adaptation: ADX trend + EMA20 touch/reclaim.
    if adx is None or adx<30 or e20 is None or e50 is None or i<1:return None
    if c[i]>e20>e50 and l[i]<=e20 and c[i]>h[i-1]:
        return {"direction":"LONG","entry_period":0,"exit_period":0,"atr":atr,"signal_close":c[i],"stop_atr":1.5,"target_r":2.0}
    if c[i]<e20<e50 and h[i]>=e20 and c[i]<l[i-1]:
        return {"direction":"SHORT","entry_period":0,"exit_period":0,"atr":atr,"signal_close":c[i],"stop_atr":1.5,"target_r":2.0}
    return None

def close_trade(acc,sid,symbol,d,pos,raw,reason,ts):
    fill=raw*(1+SLIP if d=="SHORT" else 1-SLIP)
    gross=(pos["entry_fill"]-fill)*pos["qty"] if d=="SHORT" else (fill-pos["entry_fill"])*pos["qty"]
    exit_fee=fill*pos["qty"]*FEE
    net=gross+pos["funding_usdt"]-pos["entry_fee"]-exit_fee
    acc["balance_usdt"]+=net; acc["realized_pnl_usdt"]+=net
    acc["trades"].append({"strategy_id":sid,"symbol":symbol,"direction":d,
        "entry_time_utc":pos["entry_time_utc"],"exit_time_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
        "entry_price":round(pos["entry_fill"],10),"exit_price":round(fill,10),
        "stop":pos["stop"],"target":pos["target"],"exit_reason":reason,
        "gross_pnl_usdt":round(gross,8),"fees_usdt":round(pos["entry_fee"]+exit_fee,8),
        "funding_usdt":round(pos["funding_usdt"],8),"net_pnl_usdt":round(net,8),
        "balance_after_usdt":round(acc["balance_usdt"],8)})
    acc["position"]=None

def funding_records(symbol,entry_ts):
    rows=api("/api/v5/public/funding-rate-history",{"instId":symbol,"limit":"100"})
    rows.sort(key=lambda x:int(x["fundingTime"]))
    if not rows or int(rows[0]["fundingTime"])>entry_ts:
        raise RuntimeError(f"Funding history does not cover open position for {symbol}; fail-closed.")
    return rows

def process_account(state,sid,kind,symbol,tf,candles,fundings):
    acc=state["accounts"][sid]; interval=TFS[tf]
    f=features(candles); last=acc["last_processed_candle"]
    if last is None: start=len(candles)-1
    else:
        matches=[i for i,x in enumerate(candles) if int(x[0])==int(last)]
        if not matches:raise RuntimeError(f"Last processed candle missing for {sid}; refusing state reset.")
        start=matches[-1]+1
    for i in range(max(start,1),len(candles)):
        row=candles[i]; ts=int(row[0]); op,hi,lo,cl=map(float,row[1:5])
        pos=acc["position"]
        if pos:
            if not fundings: raise RuntimeError(f"No funding records for {sid}; fail-closed.")
            if int(fundings[0]["fundingTime"])>int(pos["entry_ts"]):
                raise RuntimeError(f"Funding coverage too short for {sid}; fail-closed.")
            for rec in fundings:
                ft=int(rec["fundingTime"])
                if int(pos["entry_ts"])<ft<=ts and ft>int(pos.get("last_funding_time",pos["entry_ts"])):
                    rate=float(rec["fundingRate"])
                    pos["funding_usdt"]+=(ORDER_USDT*rate if pos["direction"]=="SHORT" else -ORDER_USDT*rate)
                    pos["last_funding_time"]=ft
        if pos and pos.get("pending_exit"):
            close_trade(acc,sid,symbol,pos["direction"],pos,op,"CHANNEL_EXIT",ts)
            pos=None
        pending=acc["pending_signal"]
        if pending and pos is None and int(pending["signal_ts"])+interval==ts:
            d=pending["direction"]; entry=op*(1-SLIP if d=="SHORT" else 1+SLIP)
            dist=float(pending["atr"])*float(pending["stop_atr"])
            stop=entry+dist if d=="SHORT" else entry-dist
            target=None
            if pending.get("target_r"):
                risk=abs(entry-stop); target=entry-risk*float(pending["target_r"]) if d=="SHORT" else entry+risk*float(pending["target_r"])
            acc["position"]={"entry_ts":ts,"entry_time_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                "entry_fill":entry,"qty":ORDER_USDT/entry,"stop":stop,"target":target,
                "entry_fee":ORDER_USDT*FEE,"funding_usdt":0.0,"last_funding_time":ts,
                "direction":d,"exit_period":int(pending.get("exit_period",0))}
            acc["pending_signal"]=None; pos=acc["position"]
        if pos:
            d=pos["direction"]
            stop_hit=(hi>=pos["stop"]) if d=="SHORT" else (lo<=pos["stop"])
            target_hit=pos["target"] is not None and ((lo<=pos["target"]) if d=="SHORT" else (hi>=pos["target"]))
            if stop_hit:
                close_trade(acc,sid,symbol,d,pos,pos["stop"],"STOP",ts+interval)
            elif target_hit:
                close_trade(acc,sid,symbol,d,pos,pos["target"],"TARGET_2R",ts+interval)
            else:
                n=pos["exit_period"]
                if n:
                    upper=max_prior(f["h"],i,n); lower=min_prior(f["l"],i,n)
                    # Channel exits are confirmed on candle close and executed next open.
                    if (d=="LONG" and lower is not None and cl<lower) or (d=="SHORT" and upper is not None and cl>upper):
                        pos["pending_exit"]=True
        if acc["position"] is None and acc["pending_signal"] is None:
            sig=direction_signal(kind,f,i)
            if sig: acc["pending_signal"]={"signal_ts":ts,**sig}
        acc["last_processed_candle"]=ts
    acc["latest_closed_candle_utc"]=datetime.fromtimestamp(int(candles[-1][0])/1000,timezone.utc).isoformat()

def metrics(acc):
    t=acc["trades"]; w=[x for x in t if x["net_pnl_usdt"]>0]; l=[x for x in t if x["net_pnl_usdt"]<0]
    gp=sum(x["net_pnl_usdt"] for x in w); gl=abs(sum(x["net_pnl_usdt"] for x in l))
    return {"starting_balance_usdt":START_BALANCE,"balance_usdt":round(acc["balance_usdt"],8),
        "realized_pnl_usdt":round(acc["realized_pnl_usdt"],8),"order_size_usdt":ORDER_USDT,
        "closed_trades":len(t),"wins":len(w),"losses":len(l),
        "win_rate_pct":round(100*len(w)/len(t),2) if t else None,
        "profit_factor":round(gp/gl,4) if gl else (None if not gp else "INF"),
        "open_position":acc["position"],"pending_signal":acc["pending_signal"],
        "latest_closed_candle_utc":acc.get("latest_closed_candle_utc"),"trades":t}

def main():
    state=json.load(open(STATE,encoding="utf-8")) if os.path.exists(STATE) else fresh_state()
    if state.get("version")!=1 or set(state.get("accounts",{}))!=set(make_ids()):
        raise RuntimeError("Unexpected paper state schema; refusing to overwrite.")
    data={}
    for symbol in SYMBOLS:
        fundings=api("/api/v5/public/funding-rate-history",{"instId":symbol,"limit":"100"})
        fundings.sort(key=lambda x:int(x["fundingTime"]))
        for tf in TFS:
            raw=api("/api/v5/market/candles",{"instId":symbol,"bar":tf,"limit":"300"})
            candles=[x for x in raw if len(x)>=9 and x[8]=="1"]; candles.reverse()
            if len(candles)<220:raise RuntimeError(f"Insufficient closed candles for {symbol} {tf}: {len(candles)}")
            data[(symbol,tf)]=(candles,fundings)
    for kind in ("DONCHIAN_ENSEMBLE","TURTLE_STYLE","HOLY_GRAIL"):
        for symbol in SYMBOLS:
            for tf in TFS:
                candles,fundings=data[(symbol,tf)]
                sid=f"{kind}_{symbol.split('-')[0]}_{tf}"
                process_account(state,sid,kind,symbol,tf,candles,fundings)
    save(STATE,state)
    report={"updated_utc":now(),"mode":"PAPER_ONLY_NO_ORDERS",
        "fee_per_side_pct":0.05,"slippage_per_side_pct":0.02,
        "funding":"Actual OKX historical funding-rate records; fail-closed if open-position coverage is insufficient.",
        "first_run_policy":"Starts from latest closed candle; no historical backfill.",
        "accounts":{sid:metrics(acc) for sid,acc in state["accounts"].items()}}
    save(REPORT,report)
    print(json.dumps({"updated_utc":report["updated_utc"],"accounts":len(report["accounts"]),
        "closed_trades":sum(x["closed_trades"] for x in report["accounts"].values()),
        "mode":report["mode"]},indent=2))

if __name__=="__main__": main()
