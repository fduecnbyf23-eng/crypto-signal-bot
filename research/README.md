# Strategy research data collection

This is a research-only workflow on the `live-trading` branch.

- Downloads closed candles from OKX public market-data endpoints.
- Collects 15m, 1H, and 4H candles for the five current symbols.
- Collects both spot instruments (the current signal bot's market data) and USDT perpetual swap instruments (the intended Futures research market).
- Uses no API keys, Telegram secrets, private account data, or order endpoints.
- Uploads the dataset as a GitHub Actions artifact; it does not change `bot.py`, `main`, or bot state.

Run **Actions → Strategy Research Data → Run workflow** and select a period. Start with 90 days. The artifact is available for 14 days.

The next stage will validate timestamp alignment and build the baseline replay before adding filters. Spot and swap results must remain separate; spot candles must not be presented as Futures execution results.
