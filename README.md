# NSE PDH/PDL Semi-Algo Scanner

Local FastAPI dashboard for NSE intraday **signal generation only**. It never places, modifies, or cancels orders.

## What it does

It retrieves the NSE equity instrument master from Upstox, obtains prior completed-session OHLC levels and batched live quotes, then emits one BUY signal on a crossing above PDH and one SELL signal on a crossing below PDL. State is stored in SQLite, so repeated quotes above/below a level do not create repeated signals. It respects 09:15–15:30 Asia/Kolkata and records signals and the manual trade journal locally.

## Start

Requires Python 3.11+ and Node is not required (the responsive dashboard is served by FastAPI).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. Enter the Upstox access token on the **Upstox** page; it remains on the local server and is never returned to the browser or written to logs. For production, use a managed secret store and PostgreSQL, put the app behind HTTPS/reverse proxy, and set a restrictive `CORS_ORIGINS` list.

## Telegram

On the Telegram page enter bot token and chat ID, test, then save. Credentials are never returned by API and are redacted from logs. One alert is sent for each persisted signal.

## Data and limits

Upstox endpoint availability, subscription coverage, instrument-master schema, request limits, and holidays are controlled by Upstox/NSE. The scanner uses chunks, bounded retries/backoff, and failure isolation. It skips symbols with missing data rather than inventing values. Previous-session levels are populated only from a completed daily candle returned by Upstox; verify holiday behavior with your subscription before use.

## API

`/api/health`, `/api/market/status`, `/api/upstox/status`, `/api/upstox/connect`, `/api/upstox/disconnect`, `/api/instruments`, `/api/scanner/status`, `/api/scanner/start`, `/api/scanner/stop`, `/api/signals`, `/api/signals/active`, `/api/settings`, `/api/telegram/test`, `/api/journal`, and `/ws/live`.

## Safety

Setup scores are rule scores, not probabilities or investment advice. Signal Entry is an observed market price, not a guaranteed fill. Test with paper/manual decisions and independently validate broker API behavior before relying on it.
