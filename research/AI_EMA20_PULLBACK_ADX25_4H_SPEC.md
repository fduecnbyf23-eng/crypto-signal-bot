# AI-designed strategy candidate: 4H EMA20 pullback + ADX25

Status: FROZEN FOR INDEPENDENT HISTORICAL TEST — NOT APPROVED FOR PAPER TRADING.

## Why this candidate
Earlier research showed that pure RSI reversal entries and several volume/VWAP combinations were regime-sensitive or failed independent periods. A trend-continuation pullback is a different hypothesis: trade only in an established bearish trend, wait for a retracement to EMA20, and require trend strength before entering. The ADX threshold is fixed at 25 before this independent replay; no parameter sweep or symbol-specific tuning is allowed.

## Frozen rules
- Venue/market: OKX USDT-SWAP Futures.
- Instruments: BTC, ETH, SOL, BNB, XRP; each replayed independently.
- Timeframe: 4Hutc candles, closed candles only.
- Direction: SHORT only.
- Trend: close < EMA20 < EMA50 < EMA200.
- Pullback trigger: current candle high >= EMA20 and current close < EMA20.
- Strength: Wilder ADX(14) >= 25 on the same closed candle.
- Entry: next 4H candle open.
- Stop: 1.5 * Wilder ATR(14) from actual entry.
- Target: fixed 2R; stop wins when both levels are touched in one candle.
- Capacity: at most one open position per symbol; no shared portfolio arbitration.
- Costs: 0.05% taker fee and 0.02% slippage per side.
- Funding: actual OKX historical funding timestamps/rates; positive funding is received by SHORT. Missing funding records fail closed.
- No leverage or liquidation claims; no private credentials, Telegram, or order endpoints.

## Independent window
- Warm-up begins: 2024-10-16 00:00 UTC.
- Entries allowed: 2024-11-26 00:00 UTC through 2025-11-25 20:00 UTC.
- Test end (exclusive): 2025-11-26 00:00 UTC.
- Data and funding coverage must be complete; any missing 4H candle or expected funding record stops the run.

## Decision gates
- Report per-symbol and aggregate closed trades, win rate, net R, expectancy, PF, max drawdown, monthly results, funding validity, and open positions at end.
- Minimum preliminary evidence: 100 aggregate closed trades and 20 per contributing symbol where feasible; net expectancy > 0 after costs/funding; PF > 1.10; no dependence on one symbol or one short month.
- If sample is below threshold, label INCONCLUSIVE_LOW_SAMPLE.
- A positive result is only a reason to consider a second untouched independent period. It does not automatically authorize paper trading.
- Do not retune on the 2024-2025 test window. Any changed rule requires a new candidate ID and a new untouched test period.

## Safety
Research only. No live orders, no paper account creation, and no production bot/workflow changes. Production bot.py, its workflow, existing paper simulators, Telegram settings, and secrets are untouched.
