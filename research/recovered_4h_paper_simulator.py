#!/usr/bin/env python3
"""Virtual-only paper simulator for recovered BNB LONG, XRP SHORT and SOL SHORT 4H strategies.
No private credentials, order endpoints, or Telegram access are used.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com"
BAR_SECONDS = 4 * 60 * 60
BAR_MS = BAR_SECONDS * 1000
START_BALANCE = 1000.0
ORDER_USDT = 10.0
FEE_SIDE = 0.0005
SLIPPAGE_SIDE = 0.0002
STATE_PATH = "research/recovered_4h_paper_state.json"
REPORT_PATH = "research/recovered_4h_paper_report.json"
REGISTRY_PATH = "research/paper_strategy_registry.json"
STRATEGIES = {
    "BNB_LONG_4H": {"symbol": "BNB-USDT-SWAP", "direction": "LONG", "rsi_low": 50.0, "rsi_high": 68.0},
    "XRP_SHORT_4H": {"symbol": "XRP-USDT-SWAP", "direction": "SHORT", "rsi_low": 32.0, "rsi_high": 50.0},
    "SOL_SHORT_4H": {"symbol": "SOL-USDT-SWAP", "direction": "SHORT", "rsi_low": 32.0, "rsi_high": 50.0},
}
STOP_ANCHOR = "SIGNAL_CANDLE_CLOSE_PROVISIONAL"
STOP_NOTE = ("The recovered notes specify 1.5 ATR but do not identify the anchor. "
             "For safe, consistent paper-only operation this simulator provisionally anchors "
             "the stop 1.5*ATR from the signal candle close; this is an explicit assumption, "
             "not a claim that the original historical test used this exact convention.")

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def api(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-Recovered4H-Paper/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX API error: {payload}")
    return payload.get("data", [])

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)

def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for i in range(period, len(values)):
        current = alpha * values[i] + (1.0 - alpha) * current
        out[i] = current
    return out

def wilder(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = (current * (period - 1) + values[i]) / period
        out[i] = current
    return out

def calc_indicators(candles):
    closes = [float(x[4]) for x in candles]
    highs = [float(x[2]) for x in candles]
    lows = [float(x[3]) for x in candles]
    e50 = ema(closes, 50)
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [None if fast[i] is None or slow[i] is None else fast[i] - slow[i] for i in range(len(closes))]
    valid = [x for x in macd if x is not None]
    sig_valid = ema(valid, 9)
    offset = len(macd) - len(sig_valid)
    macd_sig = [None] * offset + sig_valid
    gains, losses, trs = [], [], []
    for i in range(len(closes)):
        change = closes[i] - closes[i-1] if i else 0.0
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        prev = closes[i-1] if i else closes[i]
        trs.append(max(highs[i]-lows[i], abs(highs[i]-prev), abs(lows[i]-prev)))
    avg_gain, avg_loss = wilder(gains, 14), wilder(losses, 14)
    rsi = [None] * len(closes)
    for i in range(len(closes)):
        if avg_gain[i] is None or avg_loss[i] is None:
            continue
        if avg_loss[i] == 0:
            rsi[i] = 100.0 if avg_gain[i] > 0 else 50.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    atr = wilder(trs, 14)
    return closes, e50, macd, macd_sig, rsi, atr

def fresh_state():
    return {
        "version": 1, "created_utc": now_utc(),
        "accounts": {
            sid: {"starting_balance_usdt": START_BALANCE, "balance_usdt": START_BALANCE,
                  "realized_pnl_usdt": 0.0, "last_processed_candle": None,
                  "pending_signal": None, "position": None, "trades": []}
            for sid in STRATEGIES
        }
    }

def funding_cashflow(direction, notional, rate):
    # Positive funding: longs pay, shorts receive.
    return -notional * rate if direction == "LONG" else notional * rate

def close_position(account, sid, cfg, pos, raw_exit, reason, exit_ts):
    direction = cfg["direction"]
    if direction == "LONG":
        exit_fill = raw_exit * (1.0 - SLIPPAGE_SIDE)
        gross = (exit_fill - pos["entry_fill"]) * pos["quantity"]
    else:
        exit_fill = raw_exit * (1.0 + SLIPPAGE_SIDE)
        gross = (pos["entry_fill"] - exit_fill) * pos["quantity"]
    exit_fee = exit_fill * pos["quantity"] * FEE_SIDE
    net = gross + pos["funding_usdt"] - pos["entry_fee"] - exit_fee
    account["balance_usdt"] += net
    account["realized_pnl_usdt"] += net
    account["trades"].append({
        "strategy_id": sid, "symbol": cfg["symbol"], "direction": direction,
        "entry_time_utc": pos["entry_time_utc"],
        "exit_time_utc": datetime.fromtimestamp(exit_ts/1000, timezone.utc).isoformat(),
        "entry_price": round(pos["entry_fill"], 10), "exit_price": round(exit_fill, 10),
        "quantity": pos["quantity"], "stop": pos["stop"], "target": pos["target"],
        "exit_reason": reason, "gross_pnl_usdt": round(gross, 8),
        "fees_usdt": round(pos["entry_fee"]+exit_fee, 8),
        "funding_usdt": round(pos["funding_usdt"], 8), "net_pnl_usdt": round(net, 8),
        "balance_after_usdt": round(account["balance_usdt"], 8)
    })
    account["position"] = None

def apply_funding(sid, cfg, pos, records, candle_ts):
    if not records:
        raise RuntimeError(f"No funding records returned for {cfg['symbol']}; fail-closed.")
    earliest = int(records[0]["fundingTime"])
    if int(pos["entry_ts"]) < earliest:
        raise RuntimeError(f"Funding history does not cover open position for {sid}; fail-closed.")
    for rec in records:
        ft = int(rec["fundingTime"])
        if int(pos["entry_ts"]) < ft <= candle_ts and ft > int(pos.get("last_funding_time", pos["entry_ts"])):
            pos["funding_usdt"] += funding_cashflow(cfg["direction"], ORDER_USDT, float(rec["fundingRate"]))
            pos["last_funding_time"] = ft

def process_strategy(state, sid, cfg):
    account = state["accounts"][sid]
    candles = api("/api/v5/market/candles", {"instId": cfg["symbol"], "bar": "4H", "limit": "300"})
    closed = [x for x in candles if len(x) >= 9 and x[8] == "1"]
    closed.reverse()
    if len(closed) < 80:
        raise RuntimeError(f"Insufficient closed candles for {sid}: {len(closed)}")
    funding = api("/api/v5/public/funding-rate-history", {"instId": cfg["symbol"], "limit": "100"})
    funding.sort(key=lambda x: int(x["fundingTime"]))
    closes, e50, macd, macd_sig, rsi, atr = calc_indicators(closed)
    last = account["last_processed_candle"]
    if last is None:
        start = len(closed) - 1  # Start live from latest closed candle; no historical backfill.
    else:
        found = [i for i, x in enumerate(closed) if int(x[0]) == int(last)]
        if not found:
            raise RuntimeError(f"Previously processed candle missing for {sid}; refusing state reset.")
        start = found[-1] + 1
    for i in range(max(start, 1), len(closed)):
        candle = closed[i]
        ts = int(candle[0])
        o, h, l, c = map(float, candle[1:5])
        pos = account["position"]
        if pos:
            # Funding settlement timestamps are 00:00, 08:00 and 16:00 UTC.
            apply_funding(sid, cfg, pos, funding, ts)
        pending = account["pending_signal"]
        if pending and pos is None and int(pending["signal_ts"]) + BAR_MS == ts:
            direction = cfg["direction"]
            entry_fill = o * (1.0 + SLIPPAGE_SIDE if direction == "LONG" else 1.0 - SLIPPAGE_SIDE)
            distance = float(pending["atr"]) * 1.5
            if direction == "LONG":
                stop = float(pending["signal_close"]) - distance
                risk = entry_fill - stop
                target = entry_fill + 2.0 * risk
            else:
                stop = float(pending["signal_close"]) + distance
                risk = stop - entry_fill
                target = entry_fill - 2.0 * risk
            if risk <= 0:
                account["pending_signal"] = None
                account["last_processed_candle"] = ts
                continue
            qty = ORDER_USDT / entry_fill
            account["position"] = {
                "entry_ts": ts, "entry_time_utc": datetime.fromtimestamp(ts/1000, timezone.utc).isoformat(),
                "entry_fill": entry_fill, "quantity": qty, "stop": stop, "target": target,
                "entry_fee": entry_fill * qty * FEE_SIDE, "funding_usdt": 0.0,
                "last_funding_time": ts
            }
            account["pending_signal"] = None
            pos = account["position"]
        if pos:
            if cfg["direction"] == "LONG":
                if l <= pos["stop"]:
                    close_position(account, sid, cfg, pos, pos["stop"], "STOP", ts+BAR_MS)
                elif h >= pos["target"]:
                    close_position(account, sid, cfg, pos, pos["target"], "TARGET_2R", ts+BAR_MS)
            else:
                if h >= pos["stop"]:
                    close_position(account, sid, cfg, pos, pos["stop"], "STOP", ts+BAR_MS)
                elif l <= pos["target"]:
                    close_position(account, sid, cfg, pos, pos["target"], "TARGET_2R", ts+BAR_MS)
        if account["position"] is None and account["pending_signal"] is None:
            if all(x[i] is not None for x in (e50, macd, macd_sig, rsi, atr)):
                if cfg["direction"] == "LONG":
                    valid = c > e50[i] and macd[i] > macd_sig[i] and cfg["rsi_low"] <= rsi[i] <= cfg["rsi_high"]
                else:
                    valid = c < e50[i] and macd[i] < macd_sig[i] and cfg["rsi_low"] <= rsi[i] <= cfg["rsi_high"]
                if valid:
                    account["pending_signal"] = {"signal_ts": ts, "atr": atr[i], "signal_close": c}
        account["last_processed_candle"] = ts
    account["latest_closed_candle_utc"] = datetime.fromtimestamp(int(closed[-1][0])/1000, timezone.utc).isoformat()

def metrics(account):
    trades = account["trades"]
    wins = [t for t in trades if t["net_pnl_usdt"] > 0]
    losses = [t for t in trades if t["net_pnl_usdt"] < 0]
    gp = sum(t["net_pnl_usdt"] for t in wins)
    gl = abs(sum(t["net_pnl_usdt"] for t in losses))
    return {
        "starting_balance_usdt": START_BALANCE, "balance_usdt": round(account["balance_usdt"], 8),
        "realized_pnl_usdt": round(account["realized_pnl_usdt"], 8), "order_size_usdt": ORDER_USDT,
        "closed_trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": round(100*len(wins)/len(trades), 2) if trades else None,
        "profit_factor": round(gp/gl, 4) if gl else (None if not gp else "INF"),
        "open_position": account["position"], "pending_signal": account["pending_signal"],
        "latest_closed_candle_utc": account.get("latest_closed_candle_utc"),
        "trades": trades
    }

def main():
    state = load_json(STATE_PATH, fresh_state())
    if state.get("version") != 1 or set(state.get("accounts", {})) != set(STRATEGIES):
        raise RuntimeError("Unexpected paper state schema; refusing to overwrite.")
    for sid, cfg in STRATEGIES.items():
        process_strategy(state, sid, cfg)
    save_json(STATE_PATH, state)
    registry = load_json(REGISTRY_PATH, {"strategies": []})
    registry_by_id = {x["strategy_id"]: x for x in registry.get("strategies", [])}
    report = {
        "updated_utc": now_utc(), "mode": "PAPER_ONLY_NO_ORDERS",
        "stop_anchor": STOP_ANCHOR, "stop_anchor_note": STOP_NOTE,
        "fee_per_side_pct": 0.05, "slippage_per_side_pct": 0.02,
        "funding": "Actual OKX historical funding; missing/insufficient records fail closed.",
        "strategy_accounts": {}
    }
    for sid, cfg in STRATEGIES.items():
        entry = registry_by_id.get(sid, {})
        report["strategy_accounts"][sid] = {
            "strategy_name": entry.get("name", sid), "enabled": True,
            "status": "ACTIVE_PAPER_PROVISIONAL_STOP_ANCHOR",
            "symbol": cfg["symbol"], "direction": cfg["direction"],
            "metrics": metrics(state["accounts"][sid]),
            "historical_reference": entry.get("historical_reference")
        }
    save_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
