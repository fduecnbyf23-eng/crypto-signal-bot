
import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT"]
MAX_SIGNALS_PER_DAY = 15

sent_signals = set()
daily_count = 0
current_day = ""
last_reported_day = ""


STATE_FILE = "bot_state.json"
HISTORY_FILE = "signals_history.json"

def load_state():
    global sent_signals, daily_count, current_day, last_reported_day

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as file:
            state = json.load(file)

        sent_signals = set(tuple(x) for x in state.get("sent_signals", []))
        daily_count = state.get("daily_count", 0)
        current_day = state.get("current_day", "")
        last_reported_day = state.get("last_reported_day", "")


def save_state():
    with open(STATE_FILE, "w") as file:
        json.dump({
            "sent_signals": list(sent_signals),
            "daily_count": daily_count,
            "current_day": current_day,
            "last_reported_day": last_reported_day
        }, file)
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    with open(HISTORY_FILE, "r") as file:
        return json.load(file)


def save_history(history):
    with open(HISTORY_FILE, "w") as file:
        json.dump(history, file, indent=2)
def api(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "CryptoSignalBot"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]

    for value in values[1:]:
        result = value * alpha + result * (1 - alpha)

    return result


def rsi(values, period=14):
    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes[-period:]]
    losses = [max(-x, 0) for x in changes[-period:]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50

    if avg_gain == 0:
        return 0

    return 100 - 100 / (1 + avg_gain / avg_loss)


def calculate_macd(values):
    fast_values = []
    slow_values = []

    for i in range(25, len(values)):
        fast_values.append(ema(values[:i + 1], 12))
        slow_values.append(ema(values[:i + 1], 26))

    macd_values = [
        fast_values[i] - slow_values[i]
        for i in range(len(fast_values))
    ]

    macd = macd_values[-1]
    signal_line = ema(macd_values[-9:], 9)

    return macd, signal_line


def analyze(symbol):
    url = "https://www.okx.com/api/v5/market/candles?" + urllib.parse.urlencode({
        "instId": symbol,
        "bar": "15m",
        "limit": "100"
    })

    response = api(url)

    if response.get("code") != "0":
        print("Ошибка OKX:", response)
        return None

    candles = response.get("data", [])
    candles = [c for c in candles if c[8] == "1"]
    candles = list(reversed(candles))

    if len(candles) < 60:
        return None

    closed = candles

    closes = [float(c[4]) for c in closed]
    highs = [float(c[2]) for c in closed]
    lows = [float(c[3]) for c in closed]

    price = closes[-1]

    macd, signal_line = calculate_macd(closes)
    strength = rsi(closes)
    true_ranges = [] 

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr) 

    atr = sum(true_ranges[-14:]) / 14
    direction = None

    if (
        price > ema(closes, 50)
        and macd > signal_line
        and 50 < strength < 68
    ):
        direction = "BUY"

    elif (
        price < ema(closes, 50)
        and macd < signal_line
        and 32 < strength < 50
    ):
        direction = "SELL"

    if not direction:
        return None

    risk = atr * 1.5

    if direction == "BUY":
        stop = price - risk
        target = price + risk * 2
    else:
        stop = price + risk
        target = price - risk * 2

    return {
        "direction": direction,
        "price": price,
        "stop": stop,
        "target": target,
        "rsi": strength,
        "bar": closed[-1][0]
    }


def send_message(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())



def send_daily_report(history):
    global last_reported_day

    now = datetime.now(timezone.utc)

    if now.hour != 23 or now.minute < 59:
        return

    report_day = now.date().isoformat()

    if last_reported_day == report_day:
        return

    daily = [
        item for item in history
        if datetime.fromtimestamp(
            int(item["bar"]) / 1000, timezone.utc
        ).date().isoformat() == report_day
    ]

    wins = sum(1 for x in daily if x["status"] == "WIN")
    losses = sum(1 for x in daily if x["status"] == "LOSS")
    opened = sum(1 for x in daily if x["status"] == "PENDING")
    ambiguous = sum(1 for x in daily if x["status"] == "AMBIGUOUS")

    total = wins + losses
    accuracy = wins / total * 100 if total else 0

    message = (
        f"📊 ОТЧЁТ ЗА {report_day} UTC\n\n"
        f"Всего сигналов: {len(daily)}\n"
        f"✅ WIN: {wins}\n"
        f"❌ LOSS: {losses}\n"
        f"⏳ OPEN: {opened}\n"
        f"⚠️ AMBIGUOUS: {ambiguous}\n\n"
        f"Успешность: {accuracy:.1f}%"
    )

    response = send_message(message)

    if response.get("ok"):
        last_reported_day = report_day
        save_state()


def check_history(history):
    for symbol in SYMBOLS:
        pending = [
            item for item in history
            if item["symbol"] == symbol
            and item["status"] == "PENDING"
        ]

        if not pending:
            continue

        url = "https://www.okx.com/api/v5/market/candles?" + urllib.parse.urlencode({
            "instId": symbol,
            "bar": "15m",
            "limit": "100"
        })

        try:
            response = api(url)

            if response.get("code") != "0":
                print("Ошибка проверки:", response)
                continue

            candles = response.get("data", [])
            candles = [c for c in candles if c[8] == "1"]
            candles = list(reversed(candles))

            for item in pending:
                signal_bar = int(item["bar"])

                for candle in candles:
                    if int(candle[0]) <= signal_bar:
                        continue

                    high = float(candle[2])
                    low = float(candle[3])

                    if item["direction"] == "BUY":
                        tp_hit = high >= float(item["target"])
                        sl_hit = low <= float(item["stop"])
                    else:
                        tp_hit = low <= float(item["target"])
                        sl_hit = high >= float(item["stop"])

                    if tp_hit and sl_hit:
                        item["status"] = "AMBIGUOUS"
                        break
                    elif tp_hit:
                        item["status"] = "WIN"
                        break
                    elif sl_hit:
                        item["status"] = "LOSS"
                        break

        except Exception as error:
            print(f"Ошибка проверки {symbol}: {error}")

def main():  
    global daily_count, current_day
    
    load_state()
    history = load_history()
    check_history(history)
    save_history(history)
    send_daily_report(history)
    day = datetime.now(timezone.utc).date().isoformat()

    if day != current_day:
        current_day = day
        daily_count = 0
        sent_signals.clear()
        save_state()

    for symbol in SYMBOLS:
        try:
            if daily_count >= MAX_SIGNALS_PER_DAY:
                break

            result = analyze(symbol)
            print(symbol, "Результат:", result)

            if not result:
                continue

            key = (symbol, result["bar"], result["direction"])

            if key in sent_signals:
                continue

            message = (
                f"📊 CRYPTO SIGNAL: {symbol}\n"
                f"Direction: {result['direction']}\n"
                f"Price: {result['price']:.6f}\n"
                f"Stop Loss: {result['stop']:.6f}\n"
                f"Take Profit: {result['target']:.6f}\n"
                f"RSI: {result['rsi']:.2f}\n"
                f"Timeframe: 15m\n"
                f"⚠️ Educational signal. Verify before trading."
            )

            response = send_message(message)

            if response.get("ok"):
                sent_signals.add(key)
                history.append({
                    "symbol": symbol,
                    "direction": result["direction"],
                    "price": result["price"],
                    "stop": result["stop"],
                    "target": result["target"],
                    "rsi": result["rsi"],
                    "bar": result["bar"],
                    "status": "PENDING"
                })
                save_history(history)
                daily_count += 1
                save_state()

        except Exception as error:
            print(f"{symbol}: {error}")


if __name__ == "__main__":
    main()
