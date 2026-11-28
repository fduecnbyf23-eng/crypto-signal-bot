# AI MFI50 + EMA200 4H — frozen independent candidate

Candidate ID: `AI_MFI50_EMA200_4H_ALL5`

## Why this candidate was selected

The corrected 2025-2026 screening archive showed the Futures 4H MFI(14) 50-cross with EMA200 direction filter as the most promising simple candidate family. XRP was positive in both internal chronological segments (31 train trades, PF 1.975; 18 holdout trades, PF 2.310), while other symbols were mixed. This is a hypothesis, not proof of an edge. To avoid cherry-picking XRP alone, this independent replay tests the exact same frozen rule on all five symbols.

## Frozen rules

- Venue: OKX USDT-SWAP Futures.
- Symbols: BTC, ETH, SOL, BNB, XRP.
- Timeframe: 4H.
- Signal is evaluated only after a candle closes.
- LONG: MFI(14) crosses from <=50 to >50 and close is above EMA200.
- SHORT: MFI(14) crosses from >=50 to <50 and close is below EMA200.
- Entry: next 4H candle open.
- Stop: 1.5 x ATR(14); target: 2R.
- If stop and target touch in one candle, stop is assumed first. Gap-through stops exit at the opening price.
- Costs: 0.05% fee + 0.02% slippage per side.
- Futures funding is applied at historical settlement timestamps; missing/misaligned funding invalidates the run.
- One open position per symbol; no overlapping positions on a symbol.
- No parameter optimization.

## Independent period

- Warm-up begins: 2024-10-16 UTC.
- Test begins: 2024-11-26 UTC.
- Test ends (exclusive): 2025-11-26 UTC.

This is a historical regime check against a period separate from the 2025-2026 screening archive. It is not a future guarantee. If it passes, the next step is a separate forward paper-trading test using newly arriving data.

## Safety

This branch is research-only. The workflow has no credentials, no order endpoints, and no Telegram integration. Do not merge this candidate into production or enable real trading based on this test.
