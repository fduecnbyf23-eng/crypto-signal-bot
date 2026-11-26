#!/usr/bin/env python3
"""Read-only OKX public WebSocket feed smoke test. No keys, orders, or account access."""
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "BNB-USDT-SWAP", "XRP-USDT-SWAP"]
CHANNELS = ["tickers", "trades", "books5"]
TEST_SECONDS = 75
REPORT = Path("research/okx_market_data_test_report.json")


async def run_test():
    started = datetime.now(timezone.utc).isoformat()
    stats = {
        symbol: {
            channel: {"messages": 0, "last_exchange_ts": None, "last_received_utc": None, "latency_ms": []}
            for channel in CHANNELS
        }
        for symbol in SYMBOLS
    }
    samples = {}
    errors = []
    connected = False
    end_reason = "duration_elapsed"

    try:
        async with websockets.connect(
            WS_URL,
            open_timeout=20,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**20,
        ) as ws:
            connected = True
            args = [{"channel": ch, "instId": sym} for sym in SYMBOLS for ch in CHANNELS]
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            deadline = time.monotonic() + TEST_SECONDS
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(15, max(1, remaining)))
                except asyncio.TimeoutError:
                    continue
                received_ms = int(time.time() * 1000)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    errors.append("non_json_message")
                    continue

                if msg.get("event") == "error":
                    errors.append({
                        "event": "error",
                        "code": msg.get("code"),
                        "msg": msg.get("msg"),
                    })
                    continue
                if msg.get("event") in ("subscribe", "unsubscribe", "login"):
                    continue

                arg = msg.get("arg") or {}
                channel = arg.get("channel")
                symbol = arg.get("instId")
                if symbol not in stats or channel not in CHANNELS:
                    continue
                data = msg.get("data") or []
                if not data:
                    continue

                item = data[-1]
                row = stats[symbol][channel]
                row["messages"] += 1
                exchange_ts = item.get("ts")
                if exchange_ts and str(exchange_ts).isdigit():
                    exchange_ms = int(exchange_ts)
                    row["last_exchange_ts"] = exchange_ts
                    row["last_received_utc"] = datetime.now(timezone.utc).isoformat()
                    row["latency_ms"].append(received_ms - exchange_ms)

                if channel == "tickers":
                    samples.setdefault(symbol, {})["ticker"] = {
                        "last": item.get("last"),
                        "bidPx": item.get("bidPx"),
                        "askPx": item.get("askPx"),
                        "ts": item.get("ts"),
                    }
                elif channel == "trades":
                    samples.setdefault(symbol, {})["trade"] = {
                        "px": item.get("px"),
                        "sz": item.get("sz"),
                        "side": item.get("side"),
                        "ts": item.get("ts"),
                    }
                elif channel == "books5":
                    bids = item.get("bids") or []
                    asks = item.get("asks") or []
                    samples.setdefault(symbol, {})["books5"] = {
                        "bid_levels": len(bids),
                        "ask_levels": len(asks),
                        "best_bid": bids[0][0] if bids else None,
                        "best_ask": asks[0][0] if asks else None,
                        "ts": item.get("ts"),
                    }
    except Exception as exc:
        end_reason = "connection_or_runtime_error"
        errors.append(f"{type(exc).__name__}: {exc}")

    summary = {}
    required_missing = []
    for symbol in SYMBOLS:
        summary[symbol] = {}
        for channel in CHANNELS:
            row = stats[symbol][channel]
            values = row.pop("latency_ms")
            valid = [v for v in values if -30000 <= v <= 300000]
            row["latency_sample_count"] = len(valid)
            row["median_exchange_to_runner_ms"] = round(statistics.median(valid), 1) if valid else None
            row["note"] = "Runner clock difference is included; this is not a pure network-latency measurement."
            summary[symbol][channel] = row
            if channel in ("tickers", "books5") and row["messages"] == 0:
                required_missing.append(f"{symbol}:{channel}")

    passed = connected and not required_missing and not any(
        isinstance(e, dict) and e.get("event") == "error" for e in errors
    )
    report = {
        "test": "OKX_PUBLIC_WEBSOCKET_READ_ONLY",
        "mode": "READ_ONLY_NO_API_KEY_NO_ORDERS",
        "endpoint": WS_URL,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": TEST_SECONDS,
        "symbols": SYMBOLS,
        "channels": CHANNELS,
        "connected": connected,
        "passed_smoke_test": passed,
        "required_missing": required_missing,
        "end_reason": end_reason,
        "stats": summary,
        "latest_samples": samples,
        "errors": errors,
        "limitations": [
            "One short connection test does not prove long-term availability or signal accuracy.",
            "Exchange timestamp minus runner clock is only an approximate latency indicator.",
            "This test does not compare a third-party provider yet.",
            "No historical backfill, private endpoints, API keys, or trading actions are used."
        ]
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run_test())
