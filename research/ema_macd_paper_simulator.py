#!/usr/bin/env python3
"""Isolated, virtual-only EMA/MACD paper simulator. Never sends orders or Telegram messages."""
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.okx.com"
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
START_BALANCE = 1000.0
ORDER_USDT = 10.0
FEE_SIDE = 0.0005
SLIPPAGE_SIDE = 0.0002
BAR_SECONDS = 4 * 60 * 60
STATE_PATH = "research/paper_simulator_state.json"
REPORT_PATH = "research/paper_simulator_report.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def api(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoSignalAI-paper-simulator/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
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
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp, path)


def ema(values, period):
    out = []
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    for i, value in enumerate(values):
        if i < period - 1:
            out.append(None)
        elif i == period - 1:
            out.append(current)
        else:
            current = alpha * value + (1.0 - alpha) * current
            out.append(current)
    return out


def indicators(candles):
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [None if fast[i] is None or slow[i] is None else fast[i] - slow[i] for i in range(len(closes))]
    valid_macd = [x for x in macd if x is not None]
    signal_valid = ema(valid_macd, 9)
    signal = [None] * (len(macd) - len(signal_valid)) + signal_valid
    trs = []
    for i in range(len(candles)):
        prev = closes[i - 1] if i else closes[i]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    atr = [None] * len(trs)
    if len(trs) >= 14:
        current = sum(trs[:14]) / 14
        atr[13] = current
        for i in range(14, len(trs)):
            current = (current * 13 + trs[i]) / 14
            atr[i] = current
    return closes, e20, e50, e200, macd, signal, atr


def fresh_state():
    return {
        "version": 1, "created_utc": utc_now(), "starting_balance_usdt": START_BALANCE,
        "balance_usdt": START_BALANCE, "realized_pnl_usdt": 0.0,
        "symbols": {s: {"last_processed_candle": None, "pending_signal": None,
                        "position": None, "trades": [], "last_funding_time": None} for s in SYMBOLS}
    }


def apply_funding(symbol, position, funding_records, candle_ts):
    if not position:
        return
    for record in funding_records:
        ft = int(record["fundingTime"])
        if int(position["entry_ts"]) < ft <= candle_ts and ft > int(position.get("last_funding_time", position["entry_ts"])):
            rate = float(record["fundingRate"])
            cashflow = ORDER_USDT * rate  # positive funding is received by a SHORT
            position["funding_usdt"] += cashflow
            position["last_funding_time"] = ft


def close_position(state, symbol, position, exit_raw, reason, exit_ts):
    exit_fill = exit_raw * (1.0 + SLIPPAGE_SIDE)  # buy back a SHORT
    qty = position["quantity"]
    gross = (position["entry_fill"] - exit_fill) * qty
    exit_fee = ORDER_USDT * FEE_SIDE
    net = gross + position["funding_usdt"] - position["entry_fee"] - exit_fee
    state["balance_usdt"] += net
    state["realized_pnl_usdt"] += net
    trade = {
        "symbol": symbol, "direction": "SHORT", "entry_time_utc": position["entry_time_utc"],
        "exit_time_utc": datetime.fromtimestamp(exit_ts / 1000, timezone.utc).isoformat(),
        "entry_price": position["entry_fill"], "exit_price": exit_fill, "quantity": qty,
        "stop": position["stop"], "target": position["target"], "exit_reason": reason,
        "gross_pnl_usdt": round(gross, 8), "fees_usdt": round(position["entry_fee"] + exit_fee, 8),
        "funding_usdt": round(position["funding_usdt"], 8), "net_pnl_usdt": round(net, 8),
        "balance_after_usdt": round(state["balance_usdt"], 8)
    }
    state["symbols"][symbol]["trades"].append(trade)
    state["symbols"][symbol]["position"] = None


def process_symbol(state, symbol):
    data = api("/api/v5/market/candles", {"instId": symbol, "bar": "4H", "limit": "300"})
    closed = [c for c in data if len(c) >= 9 and c[8] == "1"]
    closed.reverse()
    if len(closed) < 220:
        raise RuntimeError(f"Not enough closed 4H candles for {symbol}: {len(closed)}")
    funding = api("/api/v5/public/funding-rate-history", {"instId": symbol, "limit": "100"})
    funding.sort(key=lambda x: int(x["fundingTime"]))
    closes, e20, e50, e200, macd, macd_sig, atr = indicators(closed)
    book = state["symbols"][symbol]
    last_done = book["last_processed_candle"]
    start = len(closed) - 1 if last_done is None else 0
    if last_done is not None:
        matches = [i for i, c in enumerate(closed) if int(c[0]) == int(last_done)]
        if not matches:
            raise RuntimeError(f"Last processed candle missing for {symbol}; refusing unsafe state reset")
        start = matches[-1] + 1

    for i in range(max(start, 1), len(closed)):
        candle = closed[i]
        ts = int(candle[0])
        o, h, l, c = map(float, candle[1:5])
        position = book["position"]

        # Funding is applied at the 8-hour timestamp only if the short was already open.
        if position:
            utc_hour = datetime.fromtimestamp(ts / 1000, timezone.utc).hour
            if utc_hour % 8 == 0:
                matching = [r for r in funding if int(r["fundingTime"]) == ts]
                if not matching:
                    raise RuntimeError(f"Missing expected OKX funding record for {symbol} at {ts}; refusing to assume zero funding")
            apply_funding(symbol, position, funding, ts)

        # A signal from the preceding candle enters at this candle's open.
        pending = book["pending_signal"]
        if pending and position is None and int(pending["signal_ts"]) + BAR_SECONDS * 1000 == ts:
            entry_fill = o * (1.0 - SLIPPAGE_SIDE)
            distance = float(pending["atr"]) * 1.5
            stop = entry_fill + distance
            target = entry_fill - 2.0 * distance
            qty = ORDER_USDT / entry_fill
            book["position"] = {
                "entry_ts": ts, "entry_time_utc": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(),
                "entry_fill": entry_fill, "quantity": qty, "stop": stop, "target": target,
                "entry_fee": ORDER_USDT * FEE_SIDE, "funding_usdt": 0.0, "last_funding_time": ts
            }
            book["pending_signal"] = None
            position = book["position"]

        # Evaluate the full candle after entry. If both levels touched, stop wins.
        if position:
            if h >= position["stop"]:
                close_position(state, symbol, position, position["stop"], "STOP", ts + BAR_SECONDS * 1000)
            elif l <= position["target"]:
                close_position(state, symbol, position, position["target"], "TARGET_2R", ts + BAR_SECONDS * 1000)

        # Signal only after this candle is closed; enter no earlier than next candle open.
        if book["position"] is None and book["pending_signal"] is None:
            if all(x[i] is not None for x in (e20, e50, e200, macd, macd_sig)) and all(
                x[i - 1] is not None for x in (macd, macd_sig)
            ) and atr[i] is not None:
                bearish_stack = closes[i] < e20[i] < e50[i] < e200[i]
                bearish_cross = macd[i - 1] >= macd_sig[i - 1] and macd[i] < macd_sig[i]
                if bearish_stack and bearish_cross:
                    book["pending_signal"] = {"signal_ts": ts, "atr": atr[i], "signal_close": c}

        book["last_processed_candle"] = ts

    book["latest_closed_candle_utc"] = datetime.fromtimestamp(int(closed[-1][0]) / 1000, timezone.utc).isoformat()
    book["open_position"] = book["position"]


def main():
    state = load_json(STATE_PATH, fresh_state())
    if state.get("version") != 1 or state.get("starting_balance_usdt") != START_BALANCE:
        raise RuntimeError("Unexpected simulator state version/account; refusing to overwrite")
    for symbol in SYMBOLS:
        process_symbol(state, symbol)
    save_json(STATE_PATH, state)
    summary = {
        "updated_utc": utc_now(), "mode": "PAPER_ONLY_NO_ORDERS",
        "starting_balance_usdt": START_BALANCE, "balance_usdt": round(state["balance_usdt"], 8),
        "realized_pnl_usdt": round(state["realized_pnl_usdt"], 8),
        "symbols": {}
    }
    for symbol, book in state["symbols"].items():
        trades = book["trades"]
        wins = sum(1 for t in trades if t["net_pnl_usdt"] > 0)
        summary["symbols"][symbol] = {
            "closed_trades": len(trades), "wins": wins, "losses": len(trades) - wins,
            "win_rate_pct": round(100 * wins / len(trades), 2) if trades else None,
            "net_pnl_usdt": round(sum(t["net_pnl_usdt"] for t in trades), 8),
            "open_position": book["position"], "pending_signal": book["pending_signal"],
            "latest_closed_candle_utc": book.get("latest_closed_candle_utc")
        }
    save_json(REPORT_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
