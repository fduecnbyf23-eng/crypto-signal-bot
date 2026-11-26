# Professional Strategies Paper Simulator

**Mode:** PAPER_ONLY_NO_ORDERS. This is a separate research branch and separate account/state namespace. It does not modify production bot.py, existing paper simulators, Telegram, secrets, or live trading.

## Accounts
30 independent virtual accounts: three strategy families × five instruments (BTC, ETH, SOL, BNB, XRP) × two timeframes (1H and 4H). Each starts at 1,000 USDT with a 10 USDT fixed notional position size.

## Shared execution model
- OKX USDT-SWAP public market candles, only confirmed closed candles.
- Signal is evaluated after candle close; entry at the next candle open.
- 0.05% fee and 0.02% adverse slippage per side.
- Funding uses public OKX historical funding-rate records; if the returned 100-record window does not cover an open position's entry, the run fails closed rather than inventing funding.
- If stop and target are both touched within one candle, stop is assumed first.
- First run initializes at the latest closed candle; there is no historical backfill.
- If the previously processed candle has fallen outside the 300-candle API window, the simulator stops rather than silently resetting state.

## Strategy A — Donchian Trend Ensemble (experimental adaptation)
- Entry: close breaks the previous 20-bar or 55-bar high/low.
- Filter: ADX(14) >= 20 and price on the matching side of EMA(200).
- A 55-bar breakout takes precedence over a 20-bar breakout.
- Initial stop: 2 × Wilder ATR(20) from actual entry.
- Exit: close breaks the opposite 10-bar channel for a 20-bar entry, or opposite 20-bar channel for a 55-bar entry; exit next bar open.
- This is a mechanical multi-channel adaptation, not a claim to reproduce any single manager's exact proprietary system.

## Strategy B — Turtle-style breakout (experimental adaptation)
- Entry: close breaks the previous 20-bar or 55-bar high/low; 55-bar takes precedence.
- Initial stop: 2 × Wilder ATR(20) from actual entry.
- Exit: opposite 10-bar channel after a 20-bar entry, opposite 20-bar channel after a 55-bar entry; exit next bar open.
- Fixed 10 USDT notional replaces the original Turtle volatility-based unit sizing. The original system's full portfolio rules and 20-day/55-day daily context are not claimed to be reproduced; here periods are bars on the selected 1H/4H timeframe.

## Strategy C — Holy Grail-style pullback (mechanical adaptation)
- Trend: ADX(14) >= 30; long requires close > EMA(20) > EMA(50), short requires close < EMA(20) < EMA(50).
- Pullback/reclaim: long candle touches EMA(20), closes above it and above prior candle high; short is mirrored.
- Entry next bar open.
- Stop: 1.5 × Wilder ATR(20) from entry; target 2R.
- This is a fully mechanical research adaptation of a discretionary setup, not an exact reproduction of Linda Bradford Raschke's complete discretionary method.

## Interpretation
No strategy is presumed profitable. The 1H and 4H variants are separate. A positive paper result is not proof of edge; it must be evaluated for sample size, profit factor, drawdown, costs, funding, symbol concentration, and stability across regimes before any further step.
