#!/usr/bin/env python3
"""Virtual-only RSI70 cross-down SHORT 1H paper simulator for BTC, BNB and XRP.
No private credentials, order endpoints, or Telegram access are used.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com"
BAR_MS = 60 * 60 * 1000
START_BALANCE = 1000.0
ORDER_USDT = 10.0
FEE_SIDE = 0.0005
SLIPPAGE_SIDE = 0.0002
STATE_PATH = "research/rsi70_short_1h_paper_state.json"
REPORT_PATH = "research/rsi70_short_1h_paper_report.json"
REGISTRY_PATH = "research/paper_strategy_registry.json"
STOP_ANCHOR = "SIGNAL_CANDLE_CLOSE_PROVISIONAL"
STOP_NOTE = (
    "Recovered notes specify 1.5 ATR but do not confirm the stop anchor. "
    "This simulator provisionally anchors the stop 1.5*ATR above the signal-candle close. "
    "This is an explicit paper-only assumption, not a verified original rule."
)
STRATEGIES = {
    "RSI70_BTC_SHORT_1H": {"symbol": "BTC-USDT-SWAP"},
    "RSI70_BNB_SHORT_1H": {"symbol": "BNB-USDT-SWAP"},
    "RSI70_XRP_SHORT_1H": {"symbol": "XRP-USDT-SWAP"},
}

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def api(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-RSI70-1H-Paper/1.0"})
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

def wilder(values, period):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    current = sum(values[1:period + 1]) / period
    out[period] = current
    for i in range(period + 1, len(values)):
        current = (current * (period - 1) + values[i]) / period
        out[i] = current
    return out

def indicators(candles):
    closes = [float(x[4]) for x in candles]
    highs = [float(x[2]) for x in candles]
    lows = [float(x[3]) for x in candles]
    gains, losses, trs = [0.0], [0.0], [0.0]
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    avg_gain = wilder(gains, 14)
    avg_loss = wilder(losses, 14)
    atr = wilder(trs, 14)
    rsi = [None] * len(closes)
    for i in range(len(closes)):
        if avg_gain[i] is None or avg_loss[i] is None:
            continue
        if avg_loss[i] == 0:
            rsi[i] = 100.0 if avg_gain[i] > 0 else 50.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return closes, rsi, atr

def fresh_state():
    return {
        "version": 1,
        "created_utc": now_utc(),
        "accounts": {
            sid: {
                "starting_balance_usdt": START_BALANCE,
                "balance_usdt": START_BALANCE,
                "realized_pnl_usdt": 0.0,
                "last_processed_candle": None,
                "pending_signal": None,
                "position": None,
                "trades": []
            } for sid in STRATEGIES
        }
    }

def funding_cashflow(notional, rate):
    # Positive funding: longs pay; shorts receive.
    return notional * rate

def apply_funding(sid, cfg, pos, records, candle_ts):
    if not records:
        raise RuntimeError(f"No funding records returned for {cfg['symbol']}; fail-closed.")
    earliest = int(records[0]["fundingTime"])
    if int(pos["entry_ts"]) < earliest:
        raise RuntimeError(f"Funding history does not cover open position for {sid}; fail-closed.")
    for rec in records:
        ft = int(rec["fundingTime"])
        if int(pos["entry_ts"]) < ft <= candle_ts and ft > int(pos.get("last_funding_time", pos["entry_ts"])):
            pos["funding_usdt"] += funding_cashflow(ORDER_USDT, float(rec["fundingRate"]))
            pos["last_funding_time"] = ft

def close_position(account, sid, cfg, pos, raw_exit, reason, exit_ts):
    exit_fill = raw_exit * (1.0 + SLIPPAGE_SIDE)
    gross = (pos["entry_fill"] - exit_fill) * pos["quantity"]
    exit_fee = exit_fill * pos["quantity"] * FEE_SIDE
    net = gross + pos["funding_usdt"] - pos["entry_fee"] - exit_fee
    account["balance_usdt"] += net
    account["realized_pnl_usdt"] += net
    account["trades"].append({
        "strategy_id": sid,
        "symbol": cfg["symbol"],
        "direction": "SHORT",
        "entry_time_utc": pos["entry_time_utc"],
        "exit_time_utc": datetime.fromtimestamp(exit_ts / 1000, timezone.utc).isoformat(),
        "entry_price": round(pos["entry_fill"], 10),
        "exit_price": round(exit_fill, 10),
        "quantity": pos["quantity"],
        "stop": pos["stop"],
        "target": pos["target"],
        "exit_reason": reason,
        "gross_pnl_usdt": round(gross, 8),
        "fees_usdt": round(pos["entry_fee"] + exit_fee, 8),
        "funding_usdt": round(pos["funding_usdt"], 8),
        "net_pnl_usdt": round(net, 8),
        "balance_after_usdt": round(account["balance_usdt"], 8)
    })
    account["position"] = None

def process_strategy(state, sid, cfg):
    account = state["accounts"][sid]
    candles = api("/api/v5/market/candles", {
        "instId": cfg["symbol"], "bar": "1H", "limit": "300"
    })
    closed = [x for x in candles if len(x) >= 9 and x[8] == "1"]
    closed.reverse()
    if len(closed) < 40:
        raise RuntimeError(f"Insufficient closed candles for {sid}: {len(closed)}")
    funding = api("/api/v5/public/funding-rate-history", {
        "instId": cfg["symbol"], "limit": "100"
    })
    funding.sort(key=lambda x: int(x["fundingTime"]))
    closes, rsi, atr = indicators(closed)
    last = account["last_processed_candle"]
    if last is None:
        start = len(closed) - 1
    else:
        found = [i for i, x in enumerate(closed) if int(x[0]) == int(last)]
        if not found:
            raise RuntimeError(f"Previously processed candle missing for {sid}; refusing state reset.")
        start = found[-1] + 1

    for i in range(max(start, 1), len(closed)):
        candle = closed[i]
        ts = int(candle[0])
        o, h, l = map(float, (candle[1], candle[2], candle[3]))
        pos = account["position"]
        if pos:
            apply_funding(sid, cfg, pos, funding, ts)

        pending = account["pending_signal"]
        if pending and pos is None and int(pending["signal_ts"]) + BAR_MS == ts:
            entry_fill = o * (1.0 - SLIPPAGE_SIDE)
            stop = float(pending["signal_close"]) + 1.5 * float(pending["atr"])
            risk = stop - entry_fill
            if risk <= 0:
                account["pending_signal"] = None
                account["last_processed_candle"] = ts
                continue
            target = entry_fill - 2.0 * risk
            qty = ORDER_USDT / entry_fill
            account["position"] = {
                "entry_ts": ts,
                "entry_time_utc": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(),
                "entry_fill": entry_fill,
                "quantity": qty,
                "stop": stop,
                "target": target,
                "entry_fee": entry_fill * qty * FEE_SIDE,
                "funding_usdt": 0.0,
                "last_funding_time": ts
            }
            account["pending_signal"] = None
            pos = account["position"]

        if pos:
            # Conservative intrabar ordering when stop and target are both touched.
            if h >= pos["stop"]:
                close_position(account, sid, cfg, pos, pos["stop"], "STOP", ts + BAR_MS)
            elif l <= pos["target"]:
                close_position(account, sid, cfg, pos, pos["target"], "TARGET_2R", ts + BAR_MS)

        if account["position"] is None and account["pending_signal"] is None:
            if rsi[i - 1] is not None and rsi[i] is not None and atr[i] is not None:
                if rsi[i - 1] >= 70.0 and rsi[i] < 70.0:
                    account["pending_signal"] = {
                        "signal_ts": ts,
                        "signal_close": closes[i],
                        "atr": atr[i],
                        "rsi_previous": rsi[i - 1],
                        "rsi_current": rsi[i]
                    }
        account["last_processed_candle"] = ts

    account["latest_closed_candle_utc"] = datetime.fromtimestamp(
        int(closed[-1][0]) / 1000, timezone.utc
    ).isoformat()

def metrics(account):
    trades = account["trades"]
    wins = [t for t in trades if t["net_pnl_usdt"] > 0]
    losses = [t for t in trades if t["net_pnl_usdt"] < 0]
    gross_profit = sum(t["net_pnl_usdt"] for t in wins)
    gross_loss = abs(sum(t["net_pnl_usdt"] for t in losses))
    return {
        "starting_balance_usdt": START_BALANCE,
        "balance_usdt": round(account["balance_usdt"], 8),
        "realized_pnl_usdt": round(account["realized_pnl_usdt"], 8),
        "order_size_usdt": ORDER_USDT,
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "INF"),
        "open_position": account["position"],
        "pending_signal": account["pending_signal"],
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
        "updated_utc": now_utc(),
        "mode": "PAPER_ONLY_NO_ORDERS",
        "strategy": "RSI(14) crosses down through 70; SHORT next 1H candle",
        "stop_anchor": STOP_ANCHOR,
        "stop_anchor_note": STOP_NOTE,
        "stop_distance": "1.5 * ATR(14)",
        "take_profit": "2R from actual next-candle entry",
        "fee_per_side_pct": 0.05,
        "slippage_per_side_pct": 0.02,
        "funding": "Actual OKX historical funding; missing/insufficient records fail closed.",
        "same_candle_stop_and_target": "STOP_FIRST",
        "strategy_accounts": {}
    }
    for sid, cfg in STRATEGIES.items():
        entry = registry_by_id.get(sid, {})
        report["strategy_accounts"][sid] = {
            "strategy_name": entry.get("name", sid),
            "enabled": True,
            "status": "ACTIVE_PAPER_PROVISIONAL_STOP_ANCHOR",
            "symbol": cfg["symbol"],
            "direction": "SHORT",
            "timeframe": "1H",
            "metrics": metrics(state["accounts"][sid]),
            "historical_reference": entry.get("historical_reference")
        }
    save_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
