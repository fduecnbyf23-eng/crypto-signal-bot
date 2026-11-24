# Strategy audit — 2026-11-24

## Scope and safety
- Read-only audit of `main` files and `signals_history.json`.
- Work branch: `live-trading`; at audit time its `bot.py` matched `main`.
- No strategy code, workflow, secrets, or live-trading settings were changed.
- Real order execution remains disabled.

## Historical signal summary
Source: `signals_history.json` on `main`.
- Records: 184
- Period by signal candle timestamp (UTC): 2026-11-11 23:45 through 2026-11-24 07:30
- WIN: 68
- LOSS: 115
- PENDING: 1
- Resolved signals: 183
- Win rate among resolved signals: 37.16%
- Simple theoretical gross expectancy if every WIN is +2R and every LOSS is -1R: +0.115R per resolved signal, before fees, spread, slippage, funding, and execution effects. This is not a realized PnL result.

### Direction breakdown
- SELL: 50 WIN, 60 LOSS, 1 PENDING; 45.5% win rate among resolved.
- BUY: 18 WIN, 55 LOSS; 24.7% win rate among resolved.

### Symbol breakdown
- BTC-USDT: 11 WIN, 25 LOSS, 1 PENDING; 30.6% resolved win rate.
- ETH-USDT: 11 WIN, 24 LOSS; 31.4%.
- XRP-USDT: 16 WIN, 29 LOSS; 35.6%.
- SOL-USDT: 16 WIN, 16 LOSS; 50.0%.
- BNB-USDT: 14 WIN, 21 LOSS; 40.0%.

These are descriptive historical counts, not proof that any symbol or direction will perform similarly in future markets. The sample is short and may be regime-dependent.

## Code findings in current `bot.py`
1. The strategy uses only 15-minute candles. There is no 1h/4h trend agreement, ADX, volume confirmation, support/resistance filter, or explicit volatility regime filter yet.
2. RSI uses a simple average of the last 14 gains/losses, not Wilder's smoothed RSI. EMA is initialized from the first value; MACD signal smoothing is seeded only from its last nine calculated MACD values. These implementation choices can differ from common charting-platform values.
3. ATR is a simple average of the last 14 true ranges, not Wilder ATR.
4. The outcome checker classifies a signal using later candle highs/lows. If both TP and SL are touched in one candle it labels AMBIGUOUS; the current history contains no AMBIGUOUS records. It does not model gap execution, spread, fees, slippage, funding, partial fills, or actual order-book prices.
5. The checker requests only the latest 100 closed 15m candles (about 25 hours). A signal that remains pending longer than the available candle window can be left unresolved; the history currently contains one PENDING signal.
6. History stores signal price, stop, target, RSI, signal candle time, and final status, but not the full OHLCV path or exit time/price. Therefore it cannot by itself support a fair historical replay of new filters.
7. GitHub Actions runs on a 15-minute schedule and also has a 23:59 UTC schedule. It is not a continuously running execution service. The workflow has no explicit concurrency lock; overlapping runs could read/write the same state concurrently and weaken daily caps or duplicate protection.
8. `requirements.txt` lists `python-telegram-bot`, while the current bot sends Telegram messages through the standard-library HTTP client.

## Required next test
A fair old-vs-new comparison requires historical OHLCV candles for each of the five symbols on 15m, 1h, and 4h, aligned so that only fully closed candles available at the signal time are used. The current signal history alone is insufficient.

Recommended sequence:
1. Build a reproducible candle dataset and validate timestamps/closed-candle handling.
2. Recreate the existing strategy as the baseline and verify its historical signals/outcomes against the saved history where overlap exists.
3. Add each filter independently (multi-timeframe trend, ADX, volume, support/resistance, ATR/volatility) before testing combinations.
4. Use chronological train/test or walk-forward periods; do not tune thresholds on the final test period.
5. Report trade count, win rate, gross/net R, fees and funding assumptions, drawdown, long/short and symbol breakdown, and unresolved/ambiguous cases.
6. Run the candidate in paper/demo mode before any real-money activation.

## Decision
Do not enable real orders based on this audit. No evidence here establishes a reliable live Futures edge. Preserve `main` unchanged and continue experimentation only on `live-trading`.
