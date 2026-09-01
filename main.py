"""NSE intraday analysis and paper-signal service. It never submits, changes, or cancels orders."""
import asyncio
import logging
import math
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, time as clock_time
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ============================================================
# CONFIGURATION
# ============================================================
load_dotenv()
IST = ZoneInfo("Asia/Kolkata")
UPSTOX_BASE = "https://api.upstox.com"
INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

def env_int(name: str, default: int) -> int: return int(os.getenv(name, str(default)))
def env_float(name: str, default: float) -> float: return float(os.getenv(name, str(default)))
CONFIG = {
    "timeframe": os.getenv("TIMEFRAME", "5minute"), "top_n": env_int("TOP_N_STOCKS", 20),
    "max_candles": env_int("MAX_CANDLES_PER_SYMBOL", 500), "scan_interval": env_int("SCAN_INTERVAL_SECONDS", 60),
    "ema_fast": env_int("EMA_FAST", 20), "ema_slow": env_int("EMA_SLOW", 50), "rsi_period": env_int("RSI_PERIOD", 14),
    "macd_fast": env_int("MACD_FAST", 12), "macd_slow": env_int("MACD_SLOW", 26), "macd_signal": env_int("MACD_SIGNAL", 9),
    "atr_period": env_int("ATR_PERIOD", 14), "atr_multiplier": env_float("ATR_MULTIPLIER", 1.5),
    "adx_period": env_int("ADX_PERIOD", 14), "min_relative_volume": env_float("MIN_RELATIVE_VOLUME", 1.5),
    "min_signal_score": env_float("MIN_SIGNAL_SCORE", 70), "min_rr": env_float("MIN_RR", 2),
    "risk_per_trade": env_float("RISK_PER_TRADE", .01),
    "weights": {"volume": env_float("ACTIVITY_WEIGHT_VOLUME",30), "value": env_float("ACTIVITY_WEIGHT_VALUE",25), "move": env_float("ACTIVITY_WEIGHT_MOVE",15), "range": env_float("ACTIVITY_WEIGHT_RANGE",15), "momentum": env_float("ACTIVITY_WEIGHT_MOMENTUM",15)},
}
TIMEFRAMES = {"1minute": ("minutes", 1), "5minute": ("minutes", 5), "15minute": ("minutes", 15)}

# ============================================================
# LOGGING / IN-MEMORY CACHE
# ============================================================
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nse_algo")
instrument_cache: dict[str, dict[str, Any]] = {}
candle_cache: dict[str, tuple[float, pd.DataFrame]] = {}
indicator_cache: dict[str, dict[str, Any]] = {}
signal_cache: dict[str, dict[str, Any]] = {}
scanner_cache: dict[str, Any] = {"updated_at": None, "stocks": []}
paper_trades: deque[dict[str, Any]] = deque(maxlen=500)
scanner_task: Optional[asyncio.Task] = None

# ============================================================
# UPSTOX CLIENT / INSTRUMENT MASTER
# ============================================================
class UpstoxError(Exception): pass
class UpstoxClient:
    def __init__(self) -> None:
        self.token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers={"Accept": "application/json"})

    @property
    def configured(self) -> bool: return bool(self.token and self.token != "your_access_token")
    def headers(self) -> dict[str, str]:
        if not self.configured: raise UpstoxError("UPSTOX_ACCESS_TOKEN is not configured")
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
    async def close(self) -> None: await self.client.aclose()
    async def get(self, path: str, params: Optional[dict[str, Any]] = None, absolute: bool = False) -> dict[str, Any]:
        url = path if absolute else f"{UPSTOX_BASE}{path}"
        for attempt in range(3):
            try:
                response = await self.client.get(url, headers=self.headers() if not absolute else None, params=params)
                if response.status_code == 429:
                    await asyncio.sleep(1.5 * (attempt + 1)); continue
                if response.status_code == 401: raise UpstoxError("Upstox authentication failed or token expired")
                if response.status_code in (400, 404): raise UpstoxError(f"Upstox rejected request ({response.status_code}): {response.text[:160]}")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                if attempt == 2: raise UpstoxError(f"Upstox network/API error: {exc}") from exc
                await asyncio.sleep(.7 * (attempt + 1))
        raise UpstoxError("Upstox rate limit retry exhausted")
    async def load_instruments(self) -> dict[str, dict[str, Any]]:
        global instrument_cache
        if instrument_cache: return instrument_cache
        raw = await self.get(INSTRUMENT_URL, absolute=True)
        for item in raw:
            key, symbol = item.get("instrument_key"), item.get("trading_symbol")
            if key and symbol and key.startswith("NSE_EQ|") and item.get("instrument_type") == "EQ":
                instrument_cache[symbol.upper()] = {"instrument_key": key, "symbol": symbol, "name": item.get("name", symbol), "isin": item.get("isin")}
        if not instrument_cache: raise UpstoxError("NSE equity instrument master contained no eligible instruments")
        return instrument_cache
    async def resolve(self, symbol: str) -> dict[str, Any]:
        instruments = await self.load_instruments()
        item = instruments.get(symbol.upper())
        if not item: raise UpstoxError(f"Unknown NSE equity symbol: {symbol.upper()}")
        return item
    async def candles(self, symbol: str, timeframe: str, historical: bool = False, start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
        if timeframe not in TIMEFRAMES: raise UpstoxError("timeframe must be 1minute, 5minute, or 15minute")
        item = await self.resolve(symbol); unit, interval = TIMEFRAMES[timeframe]; key = quote(item["instrument_key"], safe="")
        if historical:
            if not start or not end: raise UpstoxError("start_date and end_date are required for historical candles")
            path = f"/v3/historical-candle/{key}/{unit}/{interval}/{end.isoformat()}/{start.isoformat()}"
        else: path = f"/v3/historical-candle/intraday/{key}/{unit}/{interval}"
        data = await self.get(path)
        rows = data.get("data", {}).get("candles", [])
        if not rows: raise UpstoxError(f"No candle data available for {symbol}")
        frame = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","open_interest"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(IST)
        for col in ["open","high","low","close","volume"]: frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.dropna().sort_values("timestamp").drop_duplicates("timestamp").tail(CONFIG["max_candles"]).reset_index(drop=True)
    async def quotes(self, keys: list[str]) -> dict[str, Any]:
        if not keys: return {}
        result = await self.get("/v3/market-quote/ohlc", {"instrument_key": ",".join(keys), "interval": "1d"})
        return result.get("data", {})

upstox = UpstoxClient()

# ============================================================
# MARKET STATUS / INDICATORS / MARKET STRUCTURE
# ============================================================
def market_status(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    if now.weekday() >= 5: return "CLOSED"
    start, end = clock_time(9,15), clock_time(15,30)
    return "PRE_MARKET" if now.time() < start else "OPEN" if now.time() <= end else "CLOSED"

def indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy(); c, h, l, v = x.close, x.high, x.low, x.volume
    for n in (9, 20, 50, 200): x[f"ema_{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    delta = c.diff(); gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = gain.ewm(alpha=1/CONFIG["rsi_period"], adjust=False, min_periods=CONFIG["rsi_period"]).mean() / loss.ewm(alpha=1/CONFIG["rsi_period"], adjust=False, min_periods=CONFIG["rsi_period"]).mean().replace(0,np.nan)
    x["rsi"] = 100 - 100/(1+rs)
    macd = c.ewm(span=CONFIG["macd_fast"], adjust=False).mean() - c.ewm(span=CONFIG["macd_slow"], adjust=False).mean()
    x["macd"], x["macd_signal"], x["macd_hist"] = macd, macd.ewm(span=CONFIG["macd_signal"],adjust=False).mean(), macd - macd.ewm(span=CONFIG["macd_signal"],adjust=False).mean()
    x["roc"] = c.pct_change(10)*100
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1/CONFIG["atr_period"],adjust=False,min_periods=CONFIG["atr_period"]).mean(); x["atr_pct"] = x.atr/c*100
    plus = h.diff().where((h.diff()>-l.diff()) & (h.diff()>0),0.0); minus = (-l.diff()).where((-l.diff()>h.diff()) & (-l.diff()>0),0.0)
    atr = x.atr.replace(0,np.nan); pdi = 100*plus.ewm(alpha=1/CONFIG["adx_period"],adjust=False).mean()/atr; mdi = 100*minus.ewm(alpha=1/CONFIG["adx_period"],adjust=False).mean()/atr
    x["adx"] = (100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)).ewm(alpha=1/CONFIG["adx_period"],adjust=False,min_periods=CONFIG["adx_period"]).mean()
    x["volume_sma"] = v.rolling(20, min_periods=5).mean(); x["relative_volume"] = v/x.volume_sma.replace(0,np.nan)
    session = x.timestamp.dt.date; typical=(h+l+c)/3; x["vwap"] = (typical*v).groupby(session).cumsum()/v.groupby(session).cumsum().replace(0,np.nan)
    return x

def structure(x: pd.DataFrame) -> dict[str, Any]:
    last=x.iloc[-1]; window=x.tail(min(20,len(x))); prior=x.iloc[-21:-1] if len(x)>21 else x.iloc[:-1]
    resistance=float(prior.high.max()) if len(prior) else float(last.high); support=float(prior.low.min()) if len(prior) else float(last.low)
    opening=x[x.timestamp.dt.time <= clock_time(9,30)]
    return {"support":support,"resistance":resistance,"day_high":float(window.high.max()),"day_low":float(window.low.min()),"opening_range_high":float(opening.high.max()) if len(opening) else None,"opening_range_low":float(opening.low.min()) if len(opening) else None,"breakout":bool(last.close>resistance),"breakdown":bool(last.close<support),"retest_long":bool(last.low<=resistance and last.close>resistance),"retest_short":bool(last.high>=support and last.close<support)}

# ============================================================
# SIGNAL ENGINE / PAPER TRACKER
# ============================================================
def rounded(v: Any) -> Optional[float]: return round(float(v), 4) if pd.notna(v) else None
def build_signal(symbol: str, raw: pd.DataFrame) -> dict[str, Any]:
    x=indicators(raw); last=x.iloc[-1]; s=structure(x); reasons=[]; warnings=[]
    required=["ema_20","ema_50","rsi","macd","macd_signal","atr","adx","vwap","relative_volume"]
    if any(pd.isna(last[k]) for k in required):
        return {"symbol":symbol,"timestamp":last.timestamp.isoformat(),"signal":"WATCH","score":0,"reasons":[],"warnings":["Insufficient candles for indicator warm-up."]}
    bullish=last.close>last.vwap and last.ema_20>last.ema_50 and last.rsi>=55 and last.macd>last.macd_signal
    bearish=last.close<last.vwap and last.ema_20<last.ema_50 and last.rsi<=45 and last.macd<last.macd_signal
    sideways=last.adx<18 and last.atr_pct<0.35 and last.relative_volume<CONFIG["min_relative_volume"]
    trend_score=20 if (bullish or bearish) else 0; vwap_score=15 if (last.close>last.vwap or last.close<last.vwap) else 0
    momentum_score=20 if (last.rsi>=55 and last.macd>last.macd_signal) or (last.rsi<=45 and last.macd<last.macd_signal) else 0
    volume_score=15 if last.relative_volume>=CONFIG["min_relative_volume"] else 0
    structure_score=20 if s["breakout"] or s["breakdown"] else 0; vol_score=10 if last.adx>=20 and last.atr_pct>=.2 else 0
    score=trend_score+vwap_score+momentum_score+volume_score+structure_score+vol_score
    if bullish: reasons += ["Price above session VWAP", "EMA 20 above EMA 50", "Bullish RSI/MACD momentum"]
    if bearish: reasons += ["Price below session VWAP", "EMA 20 below EMA 50", "Bearish RSI/MACD momentum"]
    if last.relative_volume>=CONFIG["min_relative_volume"]: reasons.append(f"Relative volume {last.relative_volume:.2f}x")
    if s["breakout"]: reasons.append("Resistance breakout confirmed")
    if s["breakdown"]: reasons.append("Support breakdown confirmed")
    if sideways: warnings.append("Market is range-bound and trend strength is insufficient.")
    direction="BUY" if bullish and s["breakout"] else "SELL" if bearish and s["breakdown"] else "WATCH"
    if sideways: direction="NO_TRADE"
    if direction in ("BUY","SELL") and score<CONFIG["min_signal_score"]: direction="WATCH"; warnings.append("Confluence score is below the configured threshold.")
    entry=float(last.close); risk=float(last.atr*CONFIG["atr_multiplier"])
    stop=entry-risk if direction=="BUY" else entry+risk if direction=="SELL" else None
    target1=entry+risk*CONFIG["min_rr"] if direction=="BUY" else entry-risk*CONFIG["min_rr"] if direction=="SELL" else None
    target2=entry+risk*(CONFIG["min_rr"]+1) if direction=="BUY" else entry-risk*(CONFIG["min_rr"]+1) if direction=="SELL" else None
    return {"symbol":symbol,"timestamp":last.timestamp.isoformat(),"signal":direction,"score":round(score,1),"entry":rounded(entry) if stop else None,"stop_loss":rounded(stop),"target_1":rounded(target1),"target_2":rounded(target2),"risk_reward":CONFIG["min_rr"] if stop else None,"trend":"BULLISH" if last.ema_20>last.ema_50 else "BEARISH","vwap_status":"ABOVE" if last.close>last.vwap else "BELOW","rsi":rounded(last.rsi),"macd":rounded(last.macd),"relative_volume":rounded(last.relative_volume),"adx":rounded(last.adx),"breakout_status":"BREAKOUT" if s["breakout"] else "BREAKDOWN" if s["breakdown"] else "NONE","reasons":reasons,"warnings":warnings,"structure":s}

def track_signal(signal: dict[str, Any]) -> None:
    if signal.get("signal") not in ("BUY","SELL"): return
    if not any(t["symbol"]==signal["symbol"] and t["status"]=="OPEN" for t in paper_trades):
        paper_trades.append({**signal,"status":"OPEN","opened_at":datetime.now(IST).isoformat()})

def update_paper_trades(symbol: str, df: pd.DataFrame) -> None:
    if df.empty:return
    bar=df.iloc[-1]
    for t in paper_trades:
        if t["symbol"]!=symbol or t["status"]!="OPEN":continue
        if t["signal"]=="BUY": t["status"]="STOP_HIT" if bar.low<=t["stop_loss"] else "TARGET_HIT" if bar.high>=t["target_1"] else "OPEN"
        else: t["status"]="STOP_HIT" if bar.high>=t["stop_loss"] else "TARGET_HIT" if bar.low<=t["target_1"] else "OPEN"

# ============================================================
# STOCK SCANNER / BACKTESTER
# ============================================================
async def scan() -> list[dict[str, Any]]:
    if market_status() != "OPEN": return scanner_cache["stocks"]
    instruments=await upstox.load_instruments(); sample=list(instruments.values())[:min(250, len(instruments))]
    quotes=await upstox.quotes([i["instrument_key"] for i in sample]); rows=[]
    for item in sample:
        q=quotes.get(item["instrument_key"],{}); live=q.get("live_ohlc", q.get("ohlc",{}))
        if not live:continue
        close=float(live.get("close",0) or 0); op=float(live.get("open",close) or close); high=float(live.get("high",close) or close); low=float(live.get("low",close) or close); volume=float(live.get("volume",0) or 0)
        if close<=0:continue
        movement=abs((close-op)/op*100) if op else 0; rang=(high-low)/close*100
        score=min(100, movement*10+rang*12+math.log1p(volume)*2)
        rows.append({"symbol":item["symbol"],"instrument_key":item["instrument_key"],"ltp":round(close,2),"change_percent":round((close-op)/op*100 if op else 0,2),"volume":int(volume),"relative_volume":None,"activity_score":round(score,1)})
    rows.sort(key=lambda r:r["activity_score"],reverse=True)
    for rank,row in enumerate(rows[:CONFIG["top_n"]],1):row["rank"]=rank
    scanner_cache.update({"updated_at":datetime.now(IST).isoformat(),"stocks":rows[:CONFIG["top_n"]]}); return scanner_cache["stocks"]

def backtest_frame(symbol: str, df: pd.DataFrame, capital: float, risk_pct: float, slippage: float=.0005, cost: float=.0003) -> dict[str,Any]:
    equity=[capital]; trades=[]; active=None
    for end in range(60,len(df)):
        bar=df.iloc[end]
        if active:
            hit_stop=(bar.low<=active["stop"]) if active["side"]=="BUY" else (bar.high>=active["stop"])
            hit_target=(bar.high>=active["target"]) if active["side"]=="BUY" else (bar.low<=active["target"])
            if hit_stop or hit_target:
                exit_price=active["stop"] if hit_stop else active["target"]; exit_price*=1-slippage if active["side"]=="BUY" else 1+slippage
                pnl=(exit_price-active["entry"])*active["qty"]*(1 if active["side"]=="BUY" else -1)-active["entry"]*active["qty"]*cost*2
                capital+=pnl; trades.append(pnl); equity.append(capital); active=None
        if not active:
            sig=build_signal(symbol,df.iloc[:end+1])
            if sig["signal"] in ("BUY","SELL"):
                risk=abs(sig["entry"]-sig["stop_loss"]); qty=max(1,int((capital*risk_pct)/risk)) if risk else 0
                active={"side":sig["signal"],"entry":sig["entry"]*(1+slippage if sig["signal"]=="BUY" else 1-slippage),"stop":sig["stop_loss"],"target":sig["target_1"],"qty":qty}
    wins=[x for x in trades if x>0]; losses=[x for x in trades if x<0]; peaks=np.maximum.accumulate(equity); dd=(np.array(equity)-peaks)/peaks
    returns=np.diff(equity)/np.array(equity[:-1]) if len(equity)>1 else np.array([])
    return {"symbol":symbol,"total_trades":len(trades),"winning_trades":len(wins),"losing_trades":len(losses),"win_rate":round(100*len(wins)/len(trades),2) if trades else 0,"net_profit":round(sum(trades),2),"profit_factor":round(sum(wins)/abs(sum(losses)),2) if losses else None,"average_win":round(np.mean(wins),2) if wins else 0,"average_loss":round(np.mean(losses),2) if losses else 0,"maximum_drawdown_percent":round(abs(dd.min())*100,2) if len(dd) else 0,"expectancy":round(np.mean(trades),2) if trades else 0,"average_r":round(np.mean(trades)/(capital*risk_pct),3) if trades else 0,"sharpe_ratio":round(np.mean(returns)/np.std(returns)*np.sqrt(len(returns)),3) if len(returns)>1 and np.std(returns)>0 else None,"sortino_ratio":None,"largest_win":round(max(wins),2) if wins else 0,"largest_loss":round(min(losses),2) if losses else 0,"final_capital":round(capital,2),"warning":"Historical results are research only; they do not demonstrate profitability."}

# ============================================================
# FASTAPI ROUTES / BACKGROUND SCANNER
# ============================================================
class BacktestRequest(BaseModel):
    symbol:str; timeframe:str="5minute"; start_date:date; end_date:date; initial_capital:float=Field(gt=0); risk_per_trade:float=Field(default=.01,gt=0,le=.1)
class PositionRequest(BaseModel): capital:float=Field(gt=0); entry:float=Field(gt=0); stop_loss:float=Field(gt=0); risk_percent:float=Field(default=CONFIG["risk_per_trade"],gt=0,le=.1)
async def runner() -> None:
    while True:
        try:
            stocks=await scan()
            for row in stocks:
                try:
                    df=await upstox.candles(row["symbol"],CONFIG["timeframe"]); sig=build_signal(row["symbol"],df); signal_cache[row["symbol"]]=sig; track_signal(sig); update_paper_trades(row["symbol"],df)
                except Exception as exc: log.warning("Skipping %s: %s",row["symbol"],exc)
        except Exception as exc: log.error("Scanner cycle failed: %s",exc)
        await asyncio.sleep(max(15,CONFIG["scan_interval"]))
@asynccontextmanager
async def lifespan(app:FastAPI):
    global scanner_task
    if upstox.configured: scanner_task=asyncio.create_task(runner(),name="nse-scanner")
    yield
    if scanner_task: scanner_task.cancel()
    await upstox.close()
app=FastAPI(title="NSE Intraday Analysis",version="1.0.0",lifespan=lifespan)
def api_error(exc:Exception): raise HTTPException(status_code=503,detail=str(exc))
@app.get("/api/health")
async def health(): return {"status":"healthy","upstox":upstox.configured,"market_status":market_status(),"scanner_running":bool(scanner_task and not scanner_task.done()),"cached_symbols":len(signal_cache)}
@app.get("/api/market/status")
async def status(): return {"status":market_status(),"timezone":"Asia/Kolkata","timestamp":datetime.now(IST).isoformat()}
@app.get("/api/config")
async def config(): return {k:v for k,v in CONFIG.items() if k!="token"}
@app.get("/api/stocks")
async def stocks():
    try:return list((await upstox.load_instruments()).values())
    except Exception as e:api_error(e)
@app.get("/api/stocks/top")
async def top_stocks(): return {"updated_at":scanner_cache["updated_at"],"stocks":scanner_cache["stocks"]}
@app.post("/api/scanner/run")
async def run_scanner():
    try: return {"stocks":await scan(),"updated_at":scanner_cache["updated_at"]}
    except Exception as e:api_error(e)
@app.get("/api/candles/{symbol}")
async def candles(symbol:str,timeframe:str=Query("5minute")):
    try:return {"symbol":symbol.upper(),"timeframe":timeframe,"candles":(await upstox.candles(symbol,timeframe)).assign(timestamp=lambda d:d.timestamp.astype(str)).to_dict("records")}
    except Exception as e:api_error(e)
@app.get("/api/indicators/{symbol}")
async def indicator_endpoint(symbol:str,timeframe:str=Query("5minute")):
    try:
        x=indicators(await upstox.candles(symbol,timeframe)); row=x.iloc[-1].replace({np.nan:None}); return {k:(v.isoformat() if isinstance(v,pd.Timestamp) else rounded(v) if isinstance(v,(float,np.floating)) else v) for k,v in row.to_dict().items()}
    except Exception as e:api_error(e)
@app.get("/api/signals")
async def signals(): return {"signals":list(signal_cache.values()),"market_status":market_status()}
@app.get("/api/signals/{symbol}")
async def signal(symbol:str,timeframe:str=Query("5minute")):
    if market_status()!="OPEN": return {"symbol":symbol.upper(),"signal":"NO_TRADE","reasons":[],"warnings":["NSE market is closed; no new intraday signal is generated."]}
    try:
        result=build_signal(symbol.upper(),await upstox.candles(symbol,timeframe)); signal_cache[symbol.upper()]=result; track_signal(result); return result
    except Exception as e:api_error(e)
@app.get("/api/paper-trades")
async def paper(): return {"temporary":True,"trades":list(paper_trades)}
@app.post("/api/position-size")
async def position_size(req:PositionRequest):
    per_share=abs(req.entry-req.stop_loss)
    if not per_share: raise HTTPException(422,"entry and stop_loss must differ")
    amount=req.capital*req.risk_percent; return {"capital":req.capital,"risk_percent":req.risk_percent,"risk_amount":amount,"entry":req.entry,"stop_loss":req.stop_loss,"position_size":math.floor(amount/per_share)}
@app.post("/api/backtest")
async def backtest(req:BacktestRequest):
    try:return backtest_frame(req.symbol.upper(),await upstox.candles(req.symbol,req.timeframe,True,req.start_date,req.end_date),req.initial_capital,req.risk_per_trade)
    except Exception as e:api_error(e)

# ============================================================
# HTML DASHBOARD / STARTUP
# ============================================================
DASHBOARD='''<!doctype html><html><head><meta charset="utf-8"><title>NSE Intraday Analysis</title><style>body{font:15px system-ui;background:#0b1020;color:#e9eefb;margin:30px}h1{color:#7dd3fc}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}.card{background:#141c32;border:1px solid #293657;border-radius:10px;padding:16px}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #293657}.buy{color:#4ade80}.sell{color:#fb7185}.watch{color:#fbbf24}.muted{color:#9ca3af}</style></head><body><h1>NSE Intraday Analysis <span id="market" class="muted"></span></h1><p class="muted">Research and paper signals only — no orders are ever sent.</p><div class="grid"><section class="card"><h2>Top Active Stocks</h2><table id="stocks"></table></section><section class="card"><h2>Signals</h2><table id="signals"></table></section></div><script>const esc=x=>String(x??'—');async function load(){let[h,t,s]=await Promise.all(['/api/health','/api/stocks/top','/api/signals'].map(x=>fetch(x).then(r=>r.json())));market.textContent='• '+h.market_status;stocks.innerHTML='<tr><th>Symbol</th><th>Price</th><th>Change</th><th>Score</th></tr>'+t.stocks.map(x=>`<tr><td>${esc(x.symbol)}</td><td>${esc(x.ltp)}</td><td>${esc(x.change_percent)}%</td><td>${esc(x.activity_score)}</td></tr>`).join('');signals.innerHTML='<tr><th>Symbol</th><th>Signal</th><th>Entry</th><th>Score</th></tr>'+s.signals.map(x=>`<tr><td>${esc(x.symbol)}</td><td class="${String(x.signal).toLowerCase()}">${esc(x.signal)}</td><td>${esc(x.entry)}</td><td>${esc(x.score)}</td></tr>`).join('')}load();setInterval(load,60000)</script></body></html>'''
@app.get("/",response_class=HTMLResponse)
async def dashboard(): return DASHBOARD
if __name__=="__main__":
    import uvicorn
    uvicorn.run("main:app",host="0.0.0.0",port=env_int("PORT",8000))
