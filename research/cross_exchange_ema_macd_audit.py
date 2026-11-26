#!/usr/bin/env python3
"""Cross-exchange frozen EMA+MACD SHORT 4H audit. Public data only; never places orders."""
import csv, json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from collections import defaultdict

from indicator_features import build_features, apply_timeframe_scope

SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
START = int(datetime(2024, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2025, 11, 26, tzinfo=timezone.utc).timestamp() * 1000)
WARMUP = int(datetime(2024, 10, 17, tzinfo=timezone.utc).timestamp() * 1000)
HOUR = 3600000
FOUR_HOURS = 4 * HOUR
FEE = 0.0005
SLIPPAGE = 0.0002

def request_json(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"CryptoSignalAI-cross-exchange-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if attempt == 5: raise
            time.sleep(min(2 ** attempt, 20))

def get_binance_klines(symbol, start, end):
    rows, cursor = {}, start
    while cursor < end:
        q = urllib.parse.urlencode({"symbol":symbol,"interval":"1h","startTime":cursor,"endTime":end-1,"limit":1500})
        batch = request_json("https://fapi.binance.com/fapi/v1/klines?"+q)
        if not batch: break
        for x in batch:
            ts=int(x[0])
            if start <= ts < end and ts+HOUR <= end:
                rows[ts]={"timestamp_ms":str(ts),"utc_time":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                  "open":x[1],"high":x[2],"low":x[3],"close":x[4],"volume":x[5],
                  "volume_currency":x[5],"volume_quote":x[7],"confirm":"1"}
        nxt=int(batch[-1][0])+HOUR
        if nxt <= cursor: raise RuntimeError("Binance kline pagination stalled")
        cursor=nxt
        if len(batch)<2: break
    return [rows[k] for k in sorted(rows)]

def get_bybit_klines(symbol, start, end):
    rows, page_end = {}, end-1
    while page_end >= start:
        q=urllib.parse.urlencode({"category":"linear","symbol":symbol,"interval":"60","start":start,"end":page_end,"limit":1000})
        payload=request_json("https://api.bybit.com/v5/market/kline?"+q)
        if payload.get("retCode") != 0: raise RuntimeError("Bybit kline API: "+str(payload.get("retMsg")))
        batch=payload.get("result",{}).get("list",[])
        if not batch: break
        stamps=[]
        for x in batch:
            ts=int(x[0]); stamps.append(ts)
            if start <= ts < end and ts+HOUR <= end:
                rows[ts]={"timestamp_ms":str(ts),"utc_time":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                  "open":x[1],"high":x[2],"low":x[3],"close":x[4],"volume":x[5],
                  "volume_currency":x[5],"volume_quote":x[6],"confirm":"1"}
        oldest=min(stamps)
        if oldest <= start: break
        nxt=oldest-1
        if nxt >= page_end: raise RuntimeError("Bybit kline pagination stalled")
        page_end=nxt
        time.sleep(0.08)
    return [rows[k] for k in sorted(rows)]

def get_binance_funding(symbol):
    rows, cursor = {}, START
    while cursor < END:
        q=urllib.parse.urlencode({"symbol":symbol,"startTime":cursor,"endTime":END-1,"limit":1000})
        batch=request_json("https://fapi.binance.com/fapi/v1/fundingRate?"+q)
        if not batch: break
        for x in batch:
            ts=int(x["fundingTime"])
            if START <= ts < END: rows[ts]=float(x["fundingRate"])
        nxt=int(batch[-1]["fundingTime"])+1
        if nxt <= cursor: raise RuntimeError("Binance funding pagination stalled")
        cursor=nxt
        if len(batch)<2: break
        time.sleep(0.08)
    return rows

def get_bybit_funding(symbol):
    rows, page_end = {}, END-1
    while page_end >= START:
        q=urllib.parse.urlencode({"category":"linear","symbol":symbol,"startTime":START,"endTime":page_end,"limit":200})
        payload=request_json("https://api.bybit.com/v5/market/funding/history?"+q)
        if payload.get("retCode") != 0: raise RuntimeError("Bybit funding API: "+str(payload.get("retMsg")))
        batch=payload.get("result",{}).get("list",[])
        if not batch: break
        stamps=[]
        for x in batch:
            ts=int(x["fundingRateTimestamp"]); stamps.append(ts)
            if START <= ts < END: rows[ts]=float(x["fundingRate"])
        oldest=min(stamps)
        if oldest <= START: break
        nxt=oldest-1
        if nxt >= page_end: raise RuntimeError("Bybit funding pagination stalled")
        page_end=nxt
        time.sleep(0.08)
    return rows

def write_csv(path, rows):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    fields=list(rows[0]) if rows else []
    with open(path,"w",newline="",encoding="utf-8") as f:
        if fields:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def aggregate_4h(hourly):
    if len(hourly)%4: raise ValueError("Hourly series not divisible by four")
    out=[]
    for i in range(0,len(hourly),4):
        g=hourly[i:i+4]; ts=[int(x["timestamp_ms"]) for x in g]
        if any(b-a!=HOUR for a,b in zip(ts,ts[1:])) or ts[0]%FOUR_HOURS:
            raise ValueError("Gap, duplicate, or non-UTC-aligned hourly candle")
        out.append({"timestamp_ms":str(ts[0]),"utc_time":g[0]["utc_time"],"open":g[0]["open"],
          "high":str(max(float(x["high"]) for x in g)),"low":str(min(float(x["low"]) for x in g)),
          "close":g[-1]["close"],"volume":str(sum(float(x["volume"]) for x in g)),
          "volume_currency":str(sum(float(x["volume_currency"]) for x in g)),
          "volume_quote":str(sum(float(x["volume_quote"]) for x in g)),"confirm":"1"})
    return out

def funding_r(events, direction, entry, risk, entry_ts, exit_ts):
    # Positive funding is received by SHORT; count only events after entry through exit.
    return sum(-direction*rate*entry/risk for ts,rate in events.items() if entry_ts < ts <= exit_ts)

def run_backtest(bars, features, events, symbol, venue):
    trades=[]; pos=None
    for i,row in enumerate(bars):
        ts=int(row["timestamp_ms"]); op=float(row["open"]); hi=float(row["high"]); lo=float(row["low"])
        if pos:
            p=pos
            # Frozen priority: stop gap, target gap, then intrabar stop before target.
            if op >= p["stop"]:
                exit_price, reason = op, "STOP_GAP"
            elif op <= p["target"]:
                exit_price, reason = p["target"], "TARGET_GAP"
            elif hi >= p["stop"]:
                exit_price, reason = p["stop"], "STOP"
            elif lo <= p["target"]:
                exit_price, reason = p["target"], "TARGET"
            else:
                exit_price=reason=None
            if reason:
                gross=-(exit_price-p["entry"])/p["risk"]
                costs=(FEE+SLIPPAGE)*(p["entry"]+exit_price)/p["risk"]
                fr=funding_r(events,-1,p["entry"],p["risk"],p["entry_ts"],ts)
                trades.append({"venue":venue,"symbol":symbol,"direction":"SHORT",
                  "signal_time_utc":datetime.fromtimestamp(p["signal_ts"]/1000,timezone.utc).isoformat(),
                  "entry_time_utc":datetime.fromtimestamp(p["entry_ts"]/1000,timezone.utc).isoformat(),
                  "exit_time_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
                  "entry_price":p["entry"],"exit_price":exit_price,"stop_price":p["stop"],
                  "target_price":p["target"],"exit_reason":reason,"gross_R":gross,
                  "cost_R":costs,"funding_R":fr,"net_R":gross-costs+fr,"closed":True})
                pos=None
        if pos is None and i < len(bars)-1 and ts >= START:
            nxt=int(bars[i+1]["timestamp_ms"])
            if nxt != ts+FOUR_HOURS or nxt >= END: continue
            if features[i].get("ema_macd_short"):
                atr=features[i].get("atr14")
                if atr is None or float(atr)<=0: continue
                entry=float(bars[i+1]["open"]); risk=1.5*float(atr)
                pos={"signal_ts":ts,"entry_ts":nxt,"entry":entry,"risk":risk,
                     "stop":entry+risk,"target":entry-2*risk}
    if pos:
        last=int(bars[-1]["timestamp_ms"])+FOUR_HOURS
        mark=float(bars[-1]["close"])
        gross=-(mark-pos["entry"])/pos["risk"]
        costs=(FEE+SLIPPAGE)*(pos["entry"]+mark)/pos["risk"]
        fr=funding_r(events,-1,pos["entry"],pos["risk"],pos["entry_ts"],last)
        trades.append({"venue":venue,"symbol":symbol,"direction":"SHORT",
          "signal_time_utc":datetime.fromtimestamp(pos["signal_ts"]/1000,timezone.utc).isoformat(),
          "entry_time_utc":datetime.fromtimestamp(pos["entry_ts"]/1000,timezone.utc).isoformat(),
          "exit_time_utc":"","entry_price":pos["entry"],"exit_price":mark,
          "stop_price":pos["stop"],"target_price":pos["target"],"exit_reason":"OPEN_AT_END",
          "gross_R":gross,"cost_R":costs,"funding_R":fr,"net_R":gross-costs+fr,"closed":False})
    return trades

def summarize(trades):
    closed=[t for t in trades if t["closed"]]
    wins=[t for t in closed if t["net_R"]>0]; losses=[t for t in closed if t["net_R"]<0]
    gp=sum(t["net_R"] for t in wins); gl=abs(sum(t["net_R"] for t in losses))
    eq=peak=dd=0.0
    for t in sorted(closed,key=lambda x:x["exit_time_utc"]):
        eq+=t["net_R"]; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"trades_including_open":len(trades),"closed_trades":len(closed),
      "open_at_end":len(trades)-len(closed),"wins":len(wins),"losses":len(losses),
      "win_rate_pct":round(100*len(wins)/len(closed),4) if closed else 0,
      "net_R":round(sum(t["net_R"] for t in closed),6),
      "expectancy_R":round(sum(t["net_R"] for t in closed)/len(closed),6) if closed else 0,
      "profit_factor":round(gp/gl,6) if gl else ("INF" if gp else 0),
      "max_drawdown_R":round(dd,6)}

def main():
    out="cross-exchange-results"; os.makedirs(out,exist_ok=True)
    all_summary=[]
    venues=[
      ("BINANCE",get_binance_klines,get_binance_funding),
      ("BYBIT",get_bybit_klines,get_bybit_funding)]
    if os.getenv("SKIP_BINANCE","").lower() in ("1","true","yes"):
        venues=[v for v in venues if v[0] != "BINANCE"]
        print("Skipping Binance because the runner received HTTP 451; continuing with Bybit.",flush=True)
    for venue, candle_fn, funding_fn in venues:
      for sym in SYMBOLS:
        market_symbol=sym+"USDT"
        print(f"Downloading {venue} {market_symbol}",flush=True)
        candles=candle_fn(market_symbol,WARMUP,END)
        expected=(END-WARMUP)//HOUR
        stamps=[int(x["timestamp_ms"]) for x in candles]
        if len(candles)!=expected or stamps[0]!=WARMUP or stamps[-1]!=END-HOUR:
            raise RuntimeError(f"{venue} {sym}: hourly coverage mismatch: {len(candles)} expected {expected}")
        if any(b-a!=HOUR for a,b in zip(stamps,stamps[1:])):
            raise RuntimeError(f"{venue} {sym}: hourly gaps or duplicates")
        events=funding_fn(market_symbol)
        if not events: raise RuntimeError(f"{venue} {sym}: no historical funding returned")
        bars=aggregate_4h(candles)
        if len(bars)!=expected//4: raise RuntimeError("4H aggregate count mismatch")
        feats=apply_timeframe_scope(build_features(bars),"4H")
        trades=run_backtest(bars,feats,events,sym,venue)
        os.makedirs(f"{out}/{venue.lower()}",exist_ok=True)
        write_csv(f"{out}/{venue.lower()}/{sym}_1H.csv",candles)
        write_csv(f"{out}/{venue.lower()}/{sym}_funding.csv",
          [{"funding_time_ms":k,"rate":v} for k,v in sorted(events.items())])
        write_csv(f"{out}/{venue.lower()}/{sym}_trades.csv",trades)
        summary={"venue":venue,"symbol":sym,**summarize(trades),
          "hourly_candles":len(candles),"funding_events":len(events),
          "funding_interval_hours_observed":sorted({round((b-a)/3600000,4) for a,b in zip(sorted(events),sorted(events)[1:])}),
          "missing_hourly_candles":0,"duplicate_hourly_timestamps":len(stamps)-len(set(stamps)),
          "funding_accounting":"actual event timestamps; constant entry notional approximation"}
        all_summary.append(summary)
        print(f"  {sym}: closed={summary['closed_trades']} net_R={summary['net_R']} PF={summary['profit_factor']}",flush=True)
    with open(f"{out}/summary.json","w",encoding="utf-8") as f:
        json.dump({"strategy":"frozen EMA20<EMA50<EMA200 + bearish MACD cross, 4H SHORT",
          "window_start_utc":"2024-11-26T00:00:00Z","window_end_exclusive_utc":"2025-11-26T00:00:00Z",
          "warmup_start_utc":"2024-10-17T00:00:00Z","fee_per_side_pct":0.05,
          "slippage_per_side_pct":0.02,"stop":"1.5x signal ATR14","target":"2R",
          "stop_first":True,"one_position_per_symbol":True,"orders_generated":False,
          "results":all_summary},f,indent=2)
    print("CROSS_EXCHANGE_AUDIT_COMPLETE; research only; no orders generated.")

if __name__=="__main__": main()
