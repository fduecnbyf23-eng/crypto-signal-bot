# Chart Pattern Research — frozen first-pass protocol

Status: research design; no trading integration.
Branch: `chart-pattern-research`
Market: OKX USDT-SWAP perpetuals.
Symbols: BTC, ETH, SOL, BNB, XRP.
Timeframes: 1H and 4H, evaluated separately.

## Objective

Test each named chart formation independently, both LONG and SHORT where directionally meaningful. Only after independent out-of-sample results are reviewed may robust, non-duplicative candidates be combined into an ensemble. A green Actions run means code completed, not that a strategy is profitable.

## Pattern inventory

Repeated mentions of inverse head-and-shoulders and generic trend change are deduplicated.

1. Double top — bearish reversal.
2. Head and shoulders — bearish reversal.
3. Ascending wedge — test bearish breakdown and bullish breakout separately; prior trend context recorded.
4. Double bottom — bullish reversal.
5. Inverse head and shoulders — bullish reversal.
6. Descending wedge — test bullish breakout and bearish breakdown separately; prior trend context recorded.
7. Triple top — bearish reversal.
8. Trend reversal / break of market structure — bearish and bullish versions, explicitly a rule-based structure-break model rather than a vague visual label.
9. Bearish broadening formation (bearish expanding / broadening triangle) — expanding swing highs and lows, downside confirmation.
10. Rounding top — bearish reversal.
11. Inverted cup and handle — bearish continuation/reversal; rim and handle must be objectively identified.
12. Diamond top — bearish reversal.
13. Bullish broadening formation — expanding swing highs and lows, upside confirmation.

## Anti-lookahead rules

- Use only closed OHLCV bars.
- Swing pivots require a fixed 3 bars on both sides. A pivot at bar i becomes available only after bar i+3 has closed; no earlier use is permitted.
- Pattern geometry may use only pivots that were confirmed at the current decision timestamp.
- A breakout is valid only on a candle close beyond the frozen neckline / boundary plus the specified volatility buffer.
- Entry is at the next candle open, never at the breakout close.
- Pattern expiry, invalidation, and stop levels are fixed at signal time. No retroactive redrawing.
- If stop and target are both touched in one candle, assume stop first. A gap through stop exits at the open.
- No overlapping position per symbol/timeframe in the first-pass single-pattern replay; report trade collisions and missed opportunities.

## Initial fixed detector parameters (not optimized on the holdout)

- Pivot confirmation: 3 bars left + 3 bars right.
- Minimum separation between major pivots: 5 bars.
- Maximum formation span: 120 bars on 1H, 90 bars on 4H.
- Relative pivot/neckline tolerance: 0.50 ATR(14), computed using data available at the time.
- Breakout buffer: 0.10 ATR(14) beyond the relevant boundary.
- Maximum wait for breakout after a complete formation: 30 bars.
- Stop: beyond the formation's invalidation extreme plus 0.10 ATR(14).
- Target: fixed 2R.
- Same-bar ambiguity: stop first.
- Costs: taker fee 0.05% per side plus slippage 0.02% per side (stress test at 0.10% slippage per side).
- Funding: apply historical OKX settlement rates at exact timestamps; missing or misaligned funding invalidates the run.
- No leverage-based liquidation model is claimed; results are price-return/R research, not a live execution promise.

## Validation

- Run each pattern independently for each symbol, timeframe, and direction.
- Report count, win rate, net R after costs/funding, expectancy, profit factor, max drawdown, average hold time, and per-year/per-symbol stability.
- Keep chronological train/validation/holdout segments; detector rules and parameters are frozen before holdout is read.
- Require a minimum sample count before ranking. Low-count patterns are marked inconclusive, not winners.
- Stress costs and test sensitivity to one reasonable parameter perturbation without selecting the best variant from the holdout.
- Ensemble construction uses only patterns that pass the independent holdout and stability checks. Ensemble receives a fresh untouched forward paper test.
- If no pattern passes, report no demonstrated edge. Do not force a winner.

## Ambiguities / limitations

- "Trend reversal" is not a universally defined chart pattern; this project operationalizes it as a confirmed break of the last opposing swing structure after a prior directional swing sequence.
- "Bullish/bearish expanding triangle" is interpreted as a broadening formation with expanding swing highs and lows and a close-confirmed breakout in the stated direction.
- Visual cup/handle and diamond formations are especially subjective. Their detectors must use explicit pivot/geometry constraints and may be marked inconclusive if reliable objective rules cannot be implemented without hindsight.
- The first-pass data window and archive coverage must be verified before results are accepted. Missing candles, gaps, or funding data fail closed.

## Safety boundary

Research only. Do not edit `bot.py`, production workflows, Telegram secrets/state, or live-trading configuration. No order endpoints, API credentials, Telegram messages, or real trades.
