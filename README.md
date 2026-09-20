# Upstox Semi-Algo NSE Stock Scanner

A production-ready, Render-deployable stock scanner built with **FastAPI**, **React + Vite**, and the **Upstox API**. It screens constituents of the **NIFTY 100** and **NIFTY 200** for confirmed daily **SMA 6** and **SMA 30** crossovers using completed daily candles.

> [!IMPORTANT]
> **Semi-Algo Safety Notice**: This application is strictly an analytical scanner and screening dashboard. It **does NOT** place any buy or sell orders automatically.

---

## Features

- **Upstox API Integration**: Dynamic NSE instrument master resolution (`segment == 'NSE_EQ'`, `instrument_type == 'EQ'`) mapping trading symbols to `instrument_key`.
- **Stock Universe**: Merged NIFTY 100 and NIFTY 200 constituents with automatic deduplication.
- **Strategy Analysis**:
  - Calculates 6-period SMA and 30-period SMA on completed daily Close prices using Pandas.
  - Confirmed **BULLISH** Crossover: Previous candle `SMA6 <= SMA30`, Current completed candle `SMA6 > SMA30`.
  - Confirmed **BEARISH** Crossover: Previous candle `SMA6 >= SMA30`, Current completed candle `SMA6 < SMA30`.
  - Excludes incomplete intraday candles.
- **Ranking**: Combines bullish and bearish signals, sorts by `crossover_date DESC` (most recent first), and assigns `Rank 1, 2, 3...`.
- **Direct Access Token Input**: Connect instantly by providing your daily Upstox Access Token in the dashboard modal or via `.env`. OAuth 2.0 flow is also supported as an optional alternative.
- **Real-Time Progress Tracking**: Live progress bar (`Scanning 45 / 200`), stage descriptions, and an expandable scanner activity log terminal.
- **Results Table & Export**: Search by symbol/company, filter by signal type, sort by any column, and export clean CSV reports.
- **Database & Cleanup Policy**: Compatible with Render PostgreSQL and local SQLite. Automatically preserves the latest scan and purges older temporary runs to avoid bloat.

---

## Project Structure

```text
my first algo/
├── backend/
│   ├── main.py               # FastAPI application, CORS, routers & lifecycle
│   ├── config.py             # Pydantic Settings (secrets, URLs, tolerances)
│   ├── auth.py               # Upstox Token validation, encryption & OAuth flow
│   ├── models.py             # SQLAlchemy models (OAuthSession, ScanRun, ScanResult)
│   ├── database.py           # DB connection, migrations & cleanup policy
│   ├── universe.py           # NIFTY 100 + NIFTY 200 constituents & instrument mapping
│   ├── upstox_client.py      # Async Upstox API v2 client with rate-limiting & backoff
│   ├── scanner.py            # Historical data fetch, Pandas SMA 6/30 crossovers & ranking
│   └── requirements.txt      # Python dependencies
│
├── frontend/
│   ├── index.html            # Vite HTML template with Google Fonts (Outfit/Inter)
│   ├── vite.config.js        # Vite config with API proxy to localhost:8000
│   ├── package.json          # React, Lucide-react, Vite setup
│   └── src/
│       ├── main.jsx          # React entry point
│       ├── index.css         # Modern dark-mode styling tokens, gradients, animations
│       ├── App.jsx           # Main dashboard view
│       ├── api.js            # Fetch API client
│       └── components/
│           ├── Header.jsx         # Connection status badge, Upstox user profile, logout
│           ├── MetricsCards.jsx   # Upstox status, last scan, stocks scanned, signal counts
│           ├── ScannerControls.jsx# Run/Stop scanner buttons, live progress bar & logs
│           ├── FilterBar.jsx      # Symbol search, Bullish/Bearish filters, CSV export
│           ├── ResultsTable.jsx   # Tabular results matching exact required columns
│           └── TokenModal.jsx     # Upstox token input modal
│
├── tests/
│   ├── test_strategy.py      # Crossover and ranking unit tests
│   └── test_api.py           # FastAPI endpoint tests
│
├── .env.example              # Template for environment variables
├── render.yaml               # Render Blueprint (FastAPI web service, static frontend, postgres db)
├── Procfile                  # Process definition for web deployment
└── README.md
```

---

## Local Development

### 1. Backend Setup

```bash
# Navigate to project root
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Run FastAPI server
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The FastAPI API documentation is available at: `http://localhost:8000/docs`

### 2. Frontend Setup

In a separate terminal:

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Authentication & Upstox Access Token

Upstox access tokens are valid for 24 hours (expiring at 03:30 AM IST). You do **not** need to register developer OAuth credentials if you already have an access token:

1. Click the **Connect Upstox** button on the top right of the dashboard.
2. Paste your active Upstox access token.
3. Click **Connect Upstox**. The system validates your token against `https://api.upstox.com/v2/user/profile`, shows your user profile, and enables the scanner.

Alternatively, set `UPSTOX_ACCESS_TOKEN=your_token_here` in your `.env` file or Render environment variables.

---

## Running Automated Tests

To run the complete test suite:

```bash
python -m pytest tests -v
```

---

## Render Deployment

This project includes a ready-to-deploy [`render.yaml`](file:///render.yaml) Blueprint:

1. Push your repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com/), click **New** > **Blueprint**.
3. Connect your GitHub repository.
4. Render will automatically provision:
   - **`nse-scanner-backend`**: Python FastAPI Web Service.
   - **`nse-scanner-frontend`**: React + Vite Static Site.
   - **`nse-scanner-postgres`**: Managed PostgreSQL Database.
5. In the backend service environment variables, set `UPSTOX_ACCESS_TOKEN` (or provide it directly from the deployed dashboard).
