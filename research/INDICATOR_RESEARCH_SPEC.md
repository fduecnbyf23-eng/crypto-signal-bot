# Frozen OKX indicator research specification

Status: PREPARATION ONLY. This document and feature builder do not place orders, create trades, tune parameters, or approve paper/live trading.

## Data universe
- OKX public historical market data.
- BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT, XRP-USDT.
- Spot and USDT-SWAP perpetuals are analyzed separately.
- Closed candles only; timeframes 15m, 1H, 4H, 1Dutc.
- Futures funding joins by exact funding timestamp. Missing funding is never treated as zero.
- Comparisons use common overlapping UTC ranges within each market/timeframe.

## Indicator families and predeclared uses
| Family | Timeframes | Frozen calculation / event |
|---|---|---|
| EMA 20/50/200 | 1H, 4H, 1Dutc | EMA from close. Bull stack: close > EMA20 > EMA50 > EMA200; bear stack is inverse. EMA20 bounce: candle touches EMA20 and closes back on trend side while stack agrees. |
| RSI 14 | 15m, 1H, 4H | Wilder RSI. Oversold <30. Divergence uses confirmed 3-left/3-right pivots, latest two same-type pivots no more than 60 bars apart. Emit only on confirmation bar; never backdate. |
| Quote volume | 15m, 1H, 4H | Current quote volume >= 1.5 × SMA20 quote volume. Confirmation only, not directional signal alone. |
| VPVR | 1H, 4H | Rolling 100 bars, 24 price bins, quote volume assigned to each candle close-price bin; POC and 70% value area. Close-weighted approximation, not trade-level VPVR. |
| Bollinger Bands | 1H, 4H | SMA20 ± 2 population standard deviations. Squeeze: bandwidth in lowest 20th percentile of prior 120 available bars (minimum 60 observations). Breakout: close outside band after squeeze within prior 10 bars. |
| MACD 12/26/9 | 4H, 1Dutc | EMA-based MACD line/signal; bullish/bearish event is line/signal cross on candle close. |
| UTC daily VWAP | 15m, 1H | Typical price × quote volume, cumulative within UTC day. Bounce: candle touches VWAP and closes back across, previous close on other side. |

## Provisional execution assumptions for later backtest (not executed)
- Signal known only after candle close; entry at next candle open.
- Spot long only. SWAP long and short; report separately.
- Common baseline risk model: ATR(14), stop 1.5 ATR, target 2R.
- Separate predeclared exit experiment: RSI extreme-zone exit; do not mix with base ATR/2R.
- Conservative provisional costs: taker fee 0.05% per side and slippage 0.02% per side. These are assumptions, not the user's account fee tier.
- Funding charged/credited only at actual historical funding timestamps while SWAP position is open. If required funding interval is missing, affected segment is invalid; never substitute zero.
- If stop and target are both touched in one candle, assume stop first.
- No overlapping position per instrument in first baseline replay; no portfolio leverage optimization.

## Research sequence
1. Validate feature calculations on synthetic fixtures and verify prefix invariance (future rows cannot alter earlier features).
2. Produce feature files and counts only; inspect warm-up, NaNs, signal frequencies, timestamp alignment.
3. Freeze simple entry/exit mapping per individual family before performance backtest.
4. Test individual families chronologically, then only predeclared pairs: EMA+MACD, RSI+volume, VWAP+EMA. No grid search.
5. Keep untouched chronological holdout. Report spot/SWAP separately, per symbol and aggregate.
6. Require sufficient trade count, positive net expectancy after costs, PF >1, tolerable drawdown, and consistency across symbols/periods before any paper-trading discussion.

## Limitations
- Feature builder is not a trade simulator and its output is not evidence of profitability.
- Close-weighted VPVR is approximate because OHLCV candles lack individual trade distribution.
- Daily VWAP resets at 00:00 UTC, not an exchange-specific session.
- One year may be insufficient for robust conclusions; an independent additional period may be required.
- No production bot file, Telegram workflow, API secret, or order endpoint is used.
