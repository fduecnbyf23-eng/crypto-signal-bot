#!/usr/bin/env python3
"""Read-only OKX microstructure observer. No keys, private endpoints, or orders."""
import asyncio, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import websockets

URL = "wss://ws.okx.com:8443/ws/v5/public"
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
SECONDS = 75
OUT = Path("research/okx_microstructure_observations.jsonl")

def book_imbalance(item):
    bids, asks = item.get("bids") or [], item.get("asks") or []
    def notional(levels):
        return sum(float(x[0]) * float(x[1]) for x in levels[:5] if len(x) >= 2)
    b, a = notional(bids), notional(asks)
    return (b-a)/(b+a) if b+a else None

async def main():
    start = datetime.now(timezone.utc)
    agg = {s: {"ticker": None, "spread": [], "book_imbalance": [], "buy_notional": 0.0,
               "sell_notional": 0.0, "trades": 0, "book_updates": 0, "ticker_updates": 0}
           for s in SYMBOLS}
    errors = []
    async with websockets.connect(URL, open_timeout=20, close_timeout=5,
                                   ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
        args = [{"channel": ch, "instId": s} for s in SYMBOLS for ch in ("tickers", "trades", "books5")]
        await ws.send(json.dumps({"op":"subscribe","args":args}))
        deadline = time.monotonic() + SECONDS
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("event") == "error":
                errors.append({"code":msg.get("code"),"msg":msg.get("msg")})
                continue
            arg = msg.get("arg") or {}
            s, ch = arg.get("instId"), arg.get("channel")
            if s not in agg or not msg.get("data"):
                continue
            item = msg["data"][-1]
            a = agg[s]
            if ch == "tickers":
                last, bid, ask = (float(item[k]) for k in ("last","bidPx","askPx"))
                a["ticker"] = {"last":last,"bid":bid,"ask":ask,"exchange_ts":item.get("ts")}
                mid=(bid+ask)/2
                if mid: a["spread"].append((ask-bid)/mid*10000)
                a["ticker_updates"] += 1
            elif ch == "books5":
                v=book_imbalance(item)
                if v is not None: a["book_imbalance"].append(v)
                a["book_updates"] += 1
            elif ch == "trades":
                px, sz = float(item["px"]), float(item["sz"])
                notional=px*sz
                if item.get("side") == "buy": a["buy_notional"] += notional
                elif item.get("side") == "sell": a["sell_notional"] += notional
                a["trades"] += 1
    end = datetime.now(timezone.utc)
    rows=[]
    for s,a in agg.items():
        total=a["buy_notional"]+a["sell_notional"]
        flow=(a["buy_notional"]-a["sell_notional"])/total if total else None
        rows.append({
            "observed_at_utc":end.isoformat(),"window_seconds":SECONDS,"symbol":s,
            "last_price":a["ticker"]["last"] if a["ticker"] else None,
            "bid":a["ticker"]["bid"] if a["ticker"] else None,
            "ask":a["ticker"]["ask"] if a["ticker"] else None,
            "mean_spread_bps":round(sum(a["spread"])/len(a["spread"]),5) if a["spread"] else None,
            "mean_top5_book_imbalance":round(sum(a["book_imbalance"])/len(a["book_imbalance"]),5) if a["book_imbalance"] else None,
            "trade_flow_imbalance":round(flow,5) if flow is not None else None,
            "buy_notional_usd":round(a["buy_notional"],2),"sell_notional_usd":round(a["sell_notional"],2),
            "trade_messages":a["trades"],"book_updates":a["book_updates"],"ticker_updates":a["ticker_updates"]
        })
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("a",encoding="utf-8") as f:
        for row in rows: f.write(json.dumps(row,separators=(",",":"))+"\n")
    report={"mode":"READ_ONLY_SHADOW_OBSERVATION","started_utc":start.isoformat(),
            "finished_utc":end.isoformat(),"symbols":len(rows),"errors":errors,"rows":rows}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors or any(r["last_price"] is None or r["mean_top5_book_imbalance"] is None for r in rows):
        raise SystemExit("Required live market data missing; observation not considered complete.")

if __name__=="__main__":
    asyncio.run(main())
