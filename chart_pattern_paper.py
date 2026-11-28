"""Paper-only OKX monitor for four selected chart patterns."""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from research.chart_pattern_detectors import Candle, detect

SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
TIMEFRAMES = {"1H": "1H", "4H": "4H"}
SELECTED = {
    "ascending_wedge": "Восходящий клин",
    "rounding_top": "Круглая вершина",
    "double_top": "Двойная вершина",
    "triple_top": "Тройная вершина",
}
STATE_FILE = "chart_pattern_paper_state.json"
HISTORY_FILE = "chart_pattern_paper_history.json"


def api(symbol, bar):
    query = urllib.parse.urlencode({"instId": symbol, "bar": bar, "limit": "100"})
    req = urllib.request.Request(
        "https://www.okx.com/api/v5/market/candles?" + query,
        headers={"User-Agent": "CryptoSignalBot-PaperResearch"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode())
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX {symbol} {bar}: {payload}")
    return list(reversed(payload.get("data", [])))


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save(state, history):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def candle(row):
    return Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]),
                  float(row[4]), float(row[5]))


def atr(bars, end, period=14):
    start = max(1, end - period + 1)
    values = []
    for i in range(start, end + 1):
        prev, cur = bars[i - 1].close, bars[i]
        values.append(max(cur.high-cur.low, abs(cur.high-prev), abs(cur.low-prev)))
    return sum(values) / len(values) if values else 0.0


def settle(history, symbol, tf, closed_bars):
    pending = [x for x in history if x["symbol"] == symbol
               and x["timeframe"] == tf and x["status"] == "OPEN"]
    for item in pending:
        exit_price = None
        stop_hit = False
        exit_ts = None
        for bar in closed_bars:
            if bar.ts < item["entry_ts"]:
                continue
            if item["direction"] == "SHORT":
                stop_hit, target_hit = bar.high >= item["stop"], bar.low <= item["target"]
                gap_stop = bar.open >= item["stop"]
            else:
                stop_hit, target_hit = bar.low <= item["stop"], bar.high >= item["target"]
                gap_stop = bar.open <= item["stop"]
            if stop_hit:  # stop wins if both levels touch in one candle
                exit_price = bar.open if gap_stop else item["stop"]
                exit_ts = bar.ts
                break
            elif target_hit:
                exit_price = item["target"]
                exit_ts = bar.ts
                break
            else:
                continue
        if exit_price is None:
            continue
        sign = -1 if item["direction"] == "SHORT" else 1
            gross_r = (exit_price - item["entry"]) * sign / item["risk"]
            # Estimated taker fee 0.05% + slippage 0.02% per side.
            cost_r = 0.0007 * (item["entry"] + exit_price) / item["risk"]
            item.update({
                "status": "LOSS" if stop_hit else "WIN",
                "exit_ts": exit_ts,
                "exit_price": exit_price,
                "gross_r": gross_r,
                "cost_r": cost_r,
                "realized_r": gross_r - cost_r,
            })
            break


def detect_new(symbol, tf, raw, history, state, send_message):
    closed_rows = [r for r in raw if r[8] == "1"]
    forming_rows = [r for r in raw if r[8] != "1"]
    if not forming_rows or len(closed_rows) < 60:
        return
    closed = [candle(r) for r in closed_rows]
    entry_bar = candle(forming_rows[-1])
    bars = closed + [entry_bar]
    seen = set(state["seen_structures"])
    for sig in detect(bars):
        if sig.pattern not in SELECTED or sig.entry_index != len(bars) - 1:
            continue
        buf = 0.10 * atr(closed, sig.signal_index)
        prev_close = closed[sig.signal_index - 1].close
        first_cross = (prev_close >= sig.boundary - buf if sig.direction == "SHORT"
                       else prev_close <= sig.boundary + buf)
        if not first_cross:
            continue
        key = "|".join(map(str, [symbol, tf, sig.pattern, sig.direction, *sig.pivot_indices]))
        if key in seen:
            continue
        entry, stop = entry_bar.open, sig.invalidation
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry - 2*risk if sig.direction == "SHORT" else entry + 2*risk
        item = {
            "strategy": sig.pattern, "symbol": symbol, "timeframe": tf,
            "direction": sig.direction, "signal_ts": closed[sig.signal_index].ts,
            "entry_ts": entry_bar.ts, "entry": entry, "stop": stop,
            "target": target, "target_r": 2.0, "risk": risk,
            "status": "OPEN", "realized_r": None, "paper_only": True,
        }
        result = send_message(
            f"🧪 PAPER — ГРАФИЧЕСКАЯ МОДЕЛЬ\n"
            f"Модель: {SELECTED[sig.pattern]} ({sig.pattern})\n"
            f"Пара: {symbol}\nТаймфрейм: {tf}\nНаправление: {sig.direction}\n"
            f"Вход (open следующей свечи): {entry:.8g}\n"
            f"Стоп: {stop:.8g}\nЦель: {target:.8g} (2R)\n"
            f"Статус: PAPER / без реальных ордеров"
        )
        if isinstance(result, dict) and result.get("ok"):
            history.append(item)
            seen.add(key)
    state["seen_structures"] = sorted(seen)


def daily_report(history, state, send_message):
    day = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    if state.get("last_reported_day") == day:
        return
    rows_day = [x for x in history
                if datetime.fromtimestamp(x["signal_ts"]/1000, timezone.utc).date().isoformat() == day]
    lines = [f"🧪 PAPER-ОТЧЁТ ПО ГРАФИЧЕСКИМ МОДЕЛЯМ — {day} UTC"]
    for tf in ("1H", "4H"):
        lines.append(f"\n⏱ {tf}")
        for pattern, label in SELECTED.items():
            daily = [x for x in rows_day if x["timeframe"] == tf and x["strategy"] == pattern]
            wins = sum(x["status"] == "WIN" for x in daily)
            losses = sum(x["status"] == "LOSS" for x in daily)
            opened = sum(x["status"] == "OPEN" for x in daily)
            closed = wins + losses
            rate = wins / closed * 100 if closed else 0.0
            net = sum(x.get("realized_r") or 0.0 for x in daily)
            all_model = [x for x in history if x["timeframe"] == tf and x["strategy"] == pattern]
            all_closed = [x for x in all_model if x["status"] in ("WIN", "LOSS")]
            cumulative_r = sum(x.get("realized_r") or 0.0 for x in all_closed)
            lines.append(
                f"{label}: за день {len(daily)} | WIN {wins} | LOSS {losses} | OPEN {opened} "
                f"| win rate {rate:.1f}% | R за день {net:+.2f} | всего закрыто {len(all_closed)} "
                f"| накопленный R {cumulative_r:+.2f}"
            )
    lines.append("\nРасчёт R учитывает оценочные комиссии 0,05% и проскальзывание 0,02% на сторону; funding не включён.")
    result = send_message("\n".join(lines))
    if isinstance(result, dict) and result.get("ok"):
        state["last_reported_day"] = day


def run(send_message):
    """Paper only: fetch market candles, record hypothetical trades, never send orders."""
    state = load_json(STATE_FILE, {"seen_structures": [], "last_reported_day": ""})
    state.setdefault("seen_structures", [])
    history = load_json(HISTORY_FILE, [])
    for symbol in SYMBOLS:
        for tf, bar in TIMEFRAMES.items():
            try:
                raw = api(symbol, bar)
                closed = [candle(r) for r in raw if r[8] == "1"]
                settle(history, symbol, tf, closed)
                detect_new(symbol, tf, raw, history, state, send_message)
            except Exception as exc:
                print(f"Paper chart-pattern error {symbol} {tf}: {exc}")
    daily_report(history, state, send_message)
    save(state, history)
