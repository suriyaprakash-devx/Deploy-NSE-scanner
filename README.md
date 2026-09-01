# NSE Intraday Analysis System

A single-file FastAPI service for NSE equity intraday research using Upstox market data. It scans active instruments, calculates indicators and price structure, publishes paper signals, sizes theoretical positions, and runs candle-by-candle historical backtests. It **does not contain any order placement, modification, or cancellation capability**.

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, then set `UPSTOX_ACCESS_TOKEN` to a valid Upstox access token. Do not commit `.env`.
4. Run `uvicorn main:app --host 0.0.0.0 --port 8000` (or `python main.py`). Cloud hosts can set `PORT`.

Open `http://localhost:8000/` for the dashboard and `http://localhost:8000/docs` for interactive API documentation.

## Architecture

`main.py` contains the whole application: configuration, async Upstox HTTP client, in-memory instrument/candle/signal caches, indicator and structure calculations, scanner, signal engine, paper tracker, backtester, API, and embedded dashboard. No database or persistent trade storage is used. Restarting the server clears paper trades and caches.

Upstox calls use the NSE instrument master to resolve symbols to API-supplied instrument keys. Keys are not constructed from symbols. The app uses Upstox V3 intraday and historical candle endpoints and OHLC quotes, with retry/backoff for temporary failures and rate limiting.

## Market and strategy rules

The service respects 09:15–15:30 Asia/Kolkata on weekdays; it does not generate new signals while closed. It calculates EMA 9/20/50/200, RSI, MACD, ROC, session-reset VWAP, volume SMA/relative volume, ATR/ATR%, and ADX. A confluence score uses trend, VWAP, momentum, volume, structure, and volatility. It reports `NO_TRADE` for weak/range-bound conditions and `WATCH` until the breakout/breakdown criteria are met. Scores represent confluence strength, not probability or expected profitability.

Stops are ATR-based; targets are risk/reward based. `/api/position-size` provides a theoretical position size only.

## API

- `GET /api/health`, `/api/market/status`, `/api/config`
- `GET /api/stocks`, `/api/stocks/top`; `POST /api/scanner/run`
- `GET /api/candles/{symbol}?timeframe=5minute`
- `GET /api/indicators/{symbol}`, `/api/signals`, `/api/signals/{symbol}`
- `GET /api/paper-trades`; `POST /api/position-size`
- `POST /api/backtest` with `symbol`, `timeframe`, `start_date`, `end_date`, `initial_capital`, and optional `risk_per_trade`.

## Limitations and research warning

Live data availability, instrument eligibility, API quotas, and exchange holidays are controlled by Upstox/NSE and should be validated before use. The weekday calendar is not a substitute for an official holiday calendar. Backtests include basic slippage and transaction-cost assumptions but cannot remove look-ahead, survivorship, liquidity, fill-quality, regime-change, or overfitting risks. Test out of sample; do not treat signals or historical output as financial advice or a promise of profit.
