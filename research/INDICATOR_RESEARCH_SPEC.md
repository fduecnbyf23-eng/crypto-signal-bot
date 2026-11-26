# Frozen OKX indicator research specification

Status: FROZEN RESEARCH PLAN — preparation only. This document and feature builder do not place orders or approve paper/live trading. No parameter search is permitted after this freeze.

## 1. Data universe and isolation
- OKX public historical data only; instruments: BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT, XRP-USDT.
- Spot and USDT-SWAP are separate markets and must never be pooled into one headline result.
- Candle timeframes: 15m, 1H, 4H, 1Dutc. Only closed candles are eligible.
- All signal decisions occur after candle close. Entry is at the next candle open; no same-candle fills.
- Feature warm-up is excluded from trade statistics. Each strategy is replayed independently per instrument/timeframe; no shared capital, no cross-strategy signal arbitration, and no portfolio daily-entry cap.
- Spot is long-only. SWAP tests long and short separately.
- The one-year multi-timeframe archive is used for 15m/1H/4H and overlapping 1D results. The separate two-year daily archive is used only for 1Dutc EMA and MACD extensions. Results from different date spans are labelled separately.
- For every market/timeframe comparison, report the exact common UTC interval and number of candles. Do not silently fill missing candles or funding.

## 2. Frozen feature definitions
| Family | Timeframes | Calculation / event |
|---|---|---|
| EMA 20/50/200 | 1H, 4H, 1Dutc | EMA from close, seeded by SMA of first period. Bull stack: close > EMA20 > EMA50 > EMA200; bear stack inverse. EMA20 bounce: current candle touches EMA20 and closes back on the trend side while the matching stack is true. |
| RSI 14 | 15m, 1H, 4H | Wilder RSI. Extreme reversal event: previous RSI <=30 and current RSI >30 (long); previous RSI >=70 and current RSI <70 (short). Divergence: strict confirmed 3-left/3-right swing pivots; bullish = lower low in price and higher RSI low, bearish = higher high in price and lower RSI high; same-type pivots no more than 60 bars apart. Emit only on the third right-hand confirmation candle; never backdate. Equal-price ties are not pivots. |
| Quote volume | 15m, 1H, 4H | Current quote volume >=1.5 × SMA20 quote volume, including current closed candle. Confirmation filter only; no standalone volume strategy. |
| VPVR approximation | 1H, 4H | Rolling 100 closed candles, 24 equal-width price bins from rolling low to rolling high; assign each candle's quote volume to the bin containing its close. POC is the highest-volume bin; value area expands contiguously from POC toward the larger adjacent bin until >=70% volume. Use previous candle's VAL/VAH as levels for current bounce event. Close-weighted approximation, not trade-level VPVR. |
| Bollinger Bands | 1H, 4H | SMA20 ±2 population standard deviations. Width=(upper-lower)/middle. Squeeze if current width is at or below 20th percentile of the previous 120 available widths (minimum 60). Breakout if close is outside the current band and at least one squeeze occurred in the preceding 10 candles (current candle excluded). |
| MACD 12/26/9 | 4H, 1Dutc | EMA-seeded MACD line and signal. Bull/bear event is a line/signal cross on candle close. |
| UTC daily VWAP | 15m, 1H | Typical price=(H+L+C)/3 weighted by quote volume; cumulative from 00:00 UTC. Bounce: current candle touches current VWAP and closes across it, previous close was on the other side. Do not create bounce signals across UTC day reset. |

## 3. Frozen standalone signal maps
Every listed event is a separate strategy run. Do not merge variants into a single signal.
- EMA20 bounce: long on EMA bullish stack + EMA20 bounce; short on EMA bearish stack + EMA20 bounce.
- RSI extreme reversal: long on RSI crossing upward through 30; short on RSI crossing downward through 70.
- RSI divergence: long on confirmed bullish divergence; short on confirmed bearish divergence.
- VPVR value-area bounce: long when current low <= previous candle VAL and current close > that previous VAL; short when current high >= previous candle VAH and current close < that previous VAH. Current candle's newly calculated profile is not used as the level.
- Bollinger squeeze breakout: long on upper-band breakout after squeeze; short on lower-band breakout after squeeze.
- MACD cross: long on bullish cross; short on bearish cross.
- VWAP bounce: long/short on the respective UTC VWAP bounce event.
- Quote volume is not tested as a standalone entry strategy; it is only a same-candle confirmation filter for the RSI+volume pair.

## 4. Frozen combination maps
Only these three pairs are allowed:
1. EMA + MACD: EMA bullish/bearish stack AND MACD cross in the same direction on the same closed candle.
2. RSI + volume: RSI extreme reversal OR confirmed divergence, AND quote-volume confirmation on that same candle, in the same direction.
3. VWAP + EMA: VWAP bounce AND matching EMA stack on the same closed candle. EMA stack is evaluated on 1H/4H/1Dutc; VWAP event on 15m/1H, so this pair is only eligible on 1H. No forward-fill from future higher-timeframe candles.

No other combinations, filters, parameter grids, or symbol-specific tuning are allowed in this study.

## 5. Frozen execution and risk model
- Signal at candle close; enter at next candle open.
- Initial stop distance = 1.5 × ATR(14) from signal candle close; stop and target levels are fixed from actual entry price using that signal-candle ATR.
- Base exit: stop at 1.5 ATR or target at 2R (target distance = 2 × initial stop distance). If both touched in one candle, stop wins. If neither is hit, continue until one is hit or data ends; positions still open at end are reported separately and excluded from closed-trade win rate/PF, but their mark-to-market is reported.
- A separate RSI-extreme exit experiment is run only for RSI entry strategies: retain the same protective 1.5 ATR stop, omit fixed profit target, and exit at next candle open after a closed-candle RSI extreme in the opposite direction (long exits when RSI >=70; short exits when RSI <=30). This is reported separately from the base stop/2R test.
- One open position per instrument per strategy variant. A new signal while a position is open is ignored. Long and short variants are separate.
- Risk unit R is the initial stop distance times position quantity. Report gross R and net R after costs; do not compound returns or assume a leverage level.
- Fee assumption: 0.05% taker per side. Slippage assumption: 0.02% per side. Apply to entry and exit notional. These are conservative research assumptions, not account-specific rates. Include cost sensitivity at 0.10% and 0.20% total round-trip cost in R-equivalent reporting; do not tune entries to cost outcomes.
- Spot has no funding. SWAP funding is applied at each actual historical funding timestamp strictly after entry and at or before exit, using the funding rate and position direction. Positive funding means longs pay and shorts receive; negative funding reverses this. Missing any expected funding record while a SWAP position is open invalidates that instrument/period result; never replace missing funding with zero.
- For spot, no short trades. For SWAP, report LONG and SHORT independently and combined only as a secondary summary.
- No leverage optimization, liquidation modelling, or order-book impact is claimed. Because leverage/liquidation is not simulated, no result is evidence of live futures safety.

## 6. Chronological evaluation and rejection rules
- First inspect feature counts, warm-up, NaNs, signal frequencies, timestamp alignment and funding coverage. Do not inspect PnL to select or change rules.
- For the one-year archive, freeze 2026-07-26 00:00 UTC through the final available candle as untouched holdout; earlier entries are development/descriptive only. Development replay is cut off at the boundary, with open positions marked there. Holdout replay starts flat; only signals known at or after the boundary may enter. No rule changes after holdout results are seen.
- For two-year daily data, freeze 2026-05-25 00:00 UTC through the final available daily candle as untouched holdout. For SWAP daily development, entries begin only when the one-year funding archive begins; earlier daily data is warm-up only because no two-year funding archive exists. This daily extension is a separate evaluation, not merged into one-year intraday results.
- Run each standalone family first, then the three frozen pairs. Include per-symbol, per-market, per-timeframe, per-direction results and sample counts.
- Minimum evidence for any candidate discussion: at least 100 closed trades in the relevant aggregate and at least 20 per contributing symbol where feasible; net expectancy >0 after fees/slippage/funding; profit factor >1.10; drawdown reported and judged tolerable; positive result not concentrated in one symbol or one short subperiod. A result below sample threshold is inconclusive, not a pass.
- A candidate failing the untouched holdout is rejected for this specification. No retuning on holdout. A passing historical candidate still requires a new independent period and a separate explicit user approval before paper trading.
- Open trades, invalid funding intervals, and data-end censoring are always disclosed.

## 7. Known limitations
- VPVR is a close-weighted OHLCV approximation, not true trade-level volume profile.
- UTC VWAP is an explicitly defined 00:00 UTC session, not a venue-specific session.
- Fee/slippage assumptions may differ from actual account conditions.
- Historical OHLCV backtests do not model order-book depth, queue position, market impact, liquidation, outages, or all exchange execution mechanics.
- Feature calculation success is not evidence of strategy profitability.
- This is isolated research only; no production bot file, Telegram workflow, API secret, or order endpoint is used.


## 8. One preselected candidate for a genuinely independent replay
The first frozen comparison is complete. It produced one candidate worth a further independent check; this is not an approval:
- Instrument universe: the five listed OKX USDT-SWAP contracts only.
- Timeframe: 1H only.
- Direction: SHORT only.
- Entry: after a closed 1H candle where RSI(14) crosses from >=70 to <70; enter at the next 1H candle open.
- Stop: 1.5 × ATR(14) from actual entry; target: 2R.
- One open position per symbol; stop-first on same-candle ambiguity.
- Costs: 0.05% taker fee and 0.02% slippage per side; report the frozen 0.10% and 0.20% round-trip cost sensitivities.
- Funding: actual historical OKX funding timestamps; entry notional held constant for funding cashflow; missing expected 8-hour records invalidates the affected result.
- Independent, non-overlapping replay window: 2024-11-26 00:00 UTC inclusive to 2025-11-26 00:00 UTC exclusive. This period was not used in the first one-year comparison.
- No parameter, direction, timeframe, stop, target, or signal changes are permitted after this freeze. Do not promote any other strategy from the first comparison into this independent replay.
- Passing this independent replay would only justify discussing a separately approved paper-trading phase; it does not authorize paper or live orders.
