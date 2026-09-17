# NSE Semi-Algo Trading Scanner (Upstox API)

Production-ready NSE semi-algo trading scanner built using the **Upstox API** and an **EMA 6 / EMA 30 crossover strategy** on fully completed candles.

---

## Key Features

1. **Strategy: EMA 6 & EMA 30 Crossover**:
   - Computes EMA 6 and EMA 30 on candle close prices.
   - **BUY Signal**: Previous `EMA 6 <= EMA 30` AND Latest `EMA 6 > EMA 30`.
   - **SELL Signal**: Previous `EMA 6 >= EMA 30` AND Latest `EMA 6 < EMA 30`.
   - **Zero Look-Ahead Bias**: Crossovers are detected strictly on completed candles. In-progress/forming candles are excluded.
2. **Dynamic 5M & 10M Timeframe Selection**:
   - Seamlessly switch between **5-minute** and **10-minute** timeframes via the live dashboard.
3. **Full NSE Universe Scanning**:
   - Dynamically downloads and syncs the complete Upstox NSE Instrument Master (~2,600+ equities).
   - Rate-limited worker pool (Token-bucket at 20 req/s, concurrent workers, exponential backoff).
   - **Per-stock error isolation**: If any stock returns missing data or errors, the scanner logs and continues without stopping.
4. **Signal Ranking**:
   - Signals are ranked strictly by **most recently confirmed crossover** (newest crossover timestamp first).
   - Separate, dedicated **BUY** and **SELL** signal boards.
5. **Duplicate Protection & Persistence**:
   - Unique signal key: `date + instrument + timeframe + direction + crossover candle timestamp`.
   - Enforced by database unique constraints across restarts, reconnects, rescans, and Render redeployments.
6. **Semi-Algo Safety Guarantee**:
   - **Never trades automatically**.
   - Signals require manual user review. Users click `Manual BUY` or `Manual SELL`, verify order parameters (quantity, order type, product, limit price) in a modal, and explicitly confirm before the order is placed via Upstox API.
7. **Production Storage**:
   - Dual-mode SQLAlchemy 2.0 layer supporting **PostgreSQL** (Render / production) and **SQLite** (local zero-setup development).

---

## Quickstart (Local Development)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env` or enter credentials directly in the Dashboard UI:
```bash
cp .env.example .env
```

### 3. Run Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open your browser at `http://localhost:8000`.

---

## Deploy to Render

1. Connect your GitHub repository to Render.
2. Render will automatically detect [`render.yaml`](render.yaml) blueprint:
   - Configures the web service running FastAPI + Uvicorn.
   - Sets up managed PostgreSQL database and links `DATABASE_URL`.
3. Set `UPSTOX_ACCESS_TOKEN` in Render Environment Variables.

---

## Running Unit Tests
```bash
python -m pytest -v tests/
```
