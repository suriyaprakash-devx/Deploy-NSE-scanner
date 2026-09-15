"""NSE PDH/PDL scanner. Deliberately contains no broker order endpoint or order code."""
import asyncio, base64, json, logging, os, sqlite3, time , uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv(); IST=ZoneInfo("Asia/Kolkata"); ROOT=Path(__file__).parent; DATA=ROOT/"data"; DATA.mkdir(exist_ok=True); DB=DATA/"nse_scanner.db"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"); log=logging.getLogger("scanner")
UPSTOX="https://api.upstox.com"; MASTER="https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
DEFAULT={"scan_interval":5,"volume_filter":False,"vwap_filter":False,"trend_filter":False,"min_breakout_percent":0,"min_price":0,"max_price":100000,"min_liquidity":0,"risk_rewards":[1,2,3],"market_open":"09:15","market_close":"15:30"}

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init_db():
    c=conn(); c.executescript('''CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS instruments (instrument_key TEXT PRIMARY KEY,symbol TEXT,name TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS levels (instrument_key TEXT PRIMARY KEY,pdh REAL,pdl REAL,session_date TEXT);
    CREATE TABLE IF NOT EXISTS state (instrument_key TEXT PRIMARY KEY,previous_price REAL,buy_armed INTEGER DEFAULT 1,sell_armed INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT,instrument_key TEXT,symbol TEXT,direction TEXT,entry REAL,breakout REAL,stop_loss REAL,t1 REAL,t2 REAL,t3 REAL,score INTEGER,status TEXT,signal_time TEXT,telegram_status TEXT DEFAULT 'PENDING');
    CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT,symbol TEXT,direction TEXT,entry REAL,stop_loss REAL,t1 REAL,t2 REAL,exit REAL,result TEXT,pnl REAL,notes TEXT);'''); c.commit(); c.close()
def getv(k, default=None):
    c=conn(); r=c.execute("SELECT value FROM kv WHERE key=?",(k,)).fetchone(); c.close(); return json.loads(r[0]) if r else default
def putv(k,v):
    c=conn(); c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,json.dumps(v))); c.commit(); c.close()
def settings(): return {**DEFAULT, **getv("settings",{})}
def now(): return datetime.now(IST)
def market():
    n=now(); s=settings(); op=dt_time.fromisoformat(s["market_open"]); cl=dt_time.fromisoformat(s["market_close"])
    return "CLOSED" if n.weekday()>4 or n.time()>cl else "PRE_MARKET" if n.time()<op else "OPEN"
def mask(v): return (v[:4]+"…"+v[-4:]) if v and len(v)>10 else ("configured" if v else None)
def secret_get(name): return os.getenv(name) or getv(name,"")

class Upstox:
    def __init__(self): self.http=httpx.AsyncClient(timeout=httpx.Timeout(20), limits=httpx.Limits(max_connections=10))
    async def close(self): await self.http.aclose()
    async def request(self,path,params=None,absolute=False):
        token=secret_get("upstox_token")
        if not token: raise ValueError("Upstox is not connected")
        url=path if absolute else UPSTOX+path
        for i in range(3):
            try:
                r=await self.http.get(url,params=params,headers={"Authorization":f"Bearer {token}","Accept":"application/json"} if not absolute else {"Accept":"application/json"})
                if r.status_code==401: raise ValueError("Upstox token is invalid or expired")
                if r.status_code==429: await asyncio.sleep(2**i); continue
                r.raise_for_status(); return r.json()
            except (httpx.HTTPError, ValueError):
                if i==2: raise
                await asyncio.sleep(.5*(2**i))
        raise ValueError("Upstox request failed")
    async def validate(self): return await self.request("/v2/user/profile")
    async def instruments(self):
        # Master is public; no secret is included in its request.
        r=await self.http.get(MASTER); r.raise_for_status(); rows=r.json(); out=[]
        for x in rows:
            if x.get("instrument_type")=="EQ" and str(x.get("instrument_key","")).startswith("NSE_EQ|"):
                out.append((x["instrument_key"],x.get("trading_symbol",""),x.get("name",x.get("trading_symbol",""))))
        return out
    async def quotes(self,keys):
        data=await self.request("/v3/market-quote/ltp",{"instrument_key":",".join(keys)})
        return data.get("data",{})
    async def daily(self,key):
        from urllib.parse import quote
        data=await self.request(f"/v3/historical-candle/intraday/{quote(key,safe='')}/days/1")
        return data.get("data",{}).get("candles",[])
up=Upstox(); running=False; scan_task=None; scan_stats={"loaded":0,"scanned":0,"failed":0,"buy":0,"sell":0,"last_scan":None}

async def refresh_instruments():
    rows=await up.instruments(); c=conn(); c.executemany("INSERT INTO instruments VALUES(?,?,?,?) ON CONFLICT(instrument_key) DO UPDATE SET symbol=excluded.symbol,name=excluded.name,updated_at=excluded.updated_at",[(k,s,n,now().isoformat()) for k,s,n in rows]); c.commit(); c.close(); scan_stats["loaded"]=len(rows); return len(rows)
async def populate_level(key):
    candles=await up.daily(key)
    # Upstox returns reverse chronological candles; derive completed prior *date*, never today.
    today=now().date().isoformat(); prior=[]
    for x in candles:
        stamp=str(x[0]); day=stamp[:10]
        if day < today: prior.append(x)
    if not prior: return False
    day=max(str(x[0])[:10] for x in prior); bars=[x for x in prior if str(x[0])[:10]==day]
    high=max(float(x[2]) for x in bars); low=min(float(x[3]) for x in bars)
    c=conn(); c.execute("INSERT INTO levels VALUES(?,?,?,?) ON CONFLICT(instrument_key) DO UPDATE SET pdh=excluded.pdh,pdl=excluded.pdl,session_date=excluded.session_date",(key,high,low,day)); c.execute("INSERT OR IGNORE INTO state(instrument_key,previous_price,buy_armed,sell_armed) VALUES(?,NULL,1,1)",(key,)); c.commit(); c.close(); return True
def score(price,pdh,pdl): return 40 # filters require live fields not universally present in LTP response
async def telegram(signal):
    bot,chat=secret_get("telegram_token"),secret_get("telegram_chat")
    if not bot or not chat: return "NOT_CONFIGURED"
    msg=(f"🚨 NSE BREAKOUT ALERT\n\n{'🟢' if signal['direction']=='BUY' else '🔴'} {signal['direction']}\n"
         f"Symbol: {signal['symbol']}\nBreakout: ₹{signal['breakout']:.2f}\nSignal Entry: ₹{signal['entry']:.2f}\n"
         f"SL: ₹{signal['stop_loss']:.2f}\nT1/T2/T3: ₹{signal['t1']:.2f} / ₹{signal['t2']:.2f} / ₹{signal['t3']:.2f}\n"
         f"Setup Score: {signal['score']}/100\nTime: {signal['signal_time']} IST\nStatus: LIVE")
    try:
        r=await up.http.post(f"https://api.telegram.org/bot{bot}/sendMessage",json={"chat_id":chat,"text":msg},timeout=15); r.raise_for_status(); return "SENT"
    except httpx.HTTPError as e: log.warning("Telegram delivery failed: %s",type(e).__name__); return "FAILED"
async def process(key,symbol,price):
    c=conn(); row=c.execute("SELECT l.pdh,l.pdl,s.previous_price,s.buy_armed,s.sell_armed FROM levels l JOIN state s USING(instrument_key) WHERE l.instrument_key=?",(key,)).fetchone(); c.close()
    if not row or price<=0: return
    pdh,pdl,prev,buy,sell=row
    side = "BUY" if buy and prev is not None and prev<=pdh<price else "SELL" if sell and prev is not None and prev>=pdl>price else None
    c=conn(); c.execute("UPDATE state SET previous_price=? WHERE instrument_key=?",(price,key))
    # Re-arm only after a genuine reset back inside the prior-day range.
    if price<=pdh: c.execute("UPDATE state SET buy_armed=1 WHERE instrument_key=?",(key,))
    if price>=pdl: c.execute("UPDATE state SET sell_armed=1 WHERE instrument_key=?",(key,))
    if not side: c.commit(); c.close(); return
    risk=abs(price-(pdh if side=="BUY" else pdl))
    if risk<=0.01: c.commit(); c.close(); return
    sl=pdh if side=="BUY" else pdl; multiples=list(settings()["risk_rewards"])[:3]
    multiples=(multiples+[1,2,3])[:3] if len(multiples)<3 else multiples
    targets=[price + risk*x if side=="BUY" else price-risk*x for x in multiples]
    signal={"instrument_key":key,"symbol":symbol,"direction":side,"entry":price,"breakout":pdh if side=="BUY" else pdl,"stop_loss":sl,"t1":targets[0],"t2":targets[1],"t3":targets[2],"score":score(price,pdh,pdl),"status":"LIVE","signal_time":now().strftime("%H:%M:%S")}
    c.execute("UPDATE state SET buy_armed=0 WHERE instrument_key=?",(key,)) if side=="BUY" else c.execute("UPDATE state SET sell_armed=0 WHERE instrument_key=?",(key,))
    c.execute("INSERT INTO signals(instrument_key,symbol,direction,entry,breakout,stop_loss,t1,t2,t3,score,status,signal_time) VALUES(:instrument_key,:symbol,:direction,:entry,:breakout,:stop_loss,:t1,:t2,:t3,:score,:status,:signal_time)",signal); c.commit(); sid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.close()
    status=await telegram(signal); c=conn(); c.execute("UPDATE signals SET telegram_status=? WHERE id=?",(status,sid)); c.commit(); c.close(); scan_stats[side.lower()]+=1
async def scan_once():
    if market()!="OPEN": return
    c=conn(); rows=c.execute("SELECT i.instrument_key,i.symbol FROM instruments i JOIN levels l USING(instrument_key)").fetchall(); c.close()
    for start in range(0,len(rows),200):
        chunk=rows[start:start+200]
        try:
            quotes=await up.quotes([r[0] for r in chunk])
            for r in chunk:
                q=quotes.get(r[0],{}); price=q.get("last_price") or q.get("ltp")
                if price: await process(r[0],r[1],float(price)); scan_stats["scanned"]+=1
        except Exception as e: scan_stats["failed"]+=len(chunk); log.warning("Quote batch skipped: %s",type(e).__name__)
    scan_stats["last_scan"]=now().isoformat()
async def runner():
    while running:
        try: await scan_once()
        except Exception as e: log.exception("scanner cycle failed: %s",type(e).__name__)
        await asyncio.sleep(max(2,int(settings()["scan_interval"])))

class Token(BaseModel): access_token:str=Field(min_length=10)
class TelegramConfig(BaseModel): bot_token:str=Field(min_length=10); chat_id:str=Field(min_length=1)
class Journal(BaseModel): date:str; symbol:str; direction:str; entry:float; stop_loss:float; t1:float|None=None; t2:float|None=None; exit:float|None=None; result:str|None=None; pnl:float|None=None; notes:str|None=None
@asynccontextmanager
async def life(app): init_db(); yield; await up.close()
app=FastAPI(title="NSE Semi-Algo Scanner",lifespan=life)
origins=[x for x in os.getenv("CORS_ORIGINS","http://127.0.0.1:8000,http://localhost:8000").split(",") if x]; app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["*"],allow_headers=["*"])
def rows(q,args=()): c=conn(); r=[dict(x) for x in c.execute(q,args).fetchall()]; c.close(); return r
@app.get("/")
async def dashboard(): return FileResponse(ROOT/"frontend"/"index.html")
@app.get("/api/health")
async def health(): return {"status":"healthy","market":market(),"scanner_running":running,"upstox_connected":bool(secret_get("upstox_token"))}
@app.get("/api/market/status")
async def market_status(): return {"status":market(),"timestamp":now().isoformat(),"timezone":"Asia/Kolkata"}
@app.get("/api/upstox/status")
async def upstatus(): return {"connected":bool(secret_get("upstox_token")),"token":mask(secret_get("upstox_token"))}
@app.post("/api/upstox/connect")
async def connect(req:Token):
    old=getv("upstox_token",""); putv("upstox_token",req.access_token)
    try: p=await up.validate(); return {"connected":True,"account":p.get("data",{}).get("user_name", "Upstox")}
    except Exception as e: putv("upstox_token",old); raise HTTPException(401,"Connection failed. Check the access token.")
@app.post("/api/upstox/disconnect")
async def disconnect(): global running; running=False; putv("upstox_token",""); return {"connected":False}
@app.get("/api/instruments")
async def instruments(): return {"items":rows("SELECT * FROM instruments LIMIT 5000"),"count":len(rows("SELECT * FROM instruments"))}
@app.post("/api/instruments/refresh")
async def instruments_refresh():
    try: return {"loaded":await refresh_instruments()}
    except Exception: raise HTTPException(503,"Could not load Upstox instrument master")
@app.post("/api/levels/prepare")
async def levels_prepare(limit:int=20):
    # Bounded endpoint for controlled preparation; scanner never fans out uncontrollably.
    items=rows("SELECT instrument_key FROM instruments LIMIT ?",(min(limit,5000),)); ok=0
    for x in items:
        try: ok+=await populate_level(x["instrument_key"])
        except Exception: scan_stats["failed"]+=1
    return {"prepared":ok,"requested":len(items)}
@app.get("/api/scanner/status")
async def scanner_status(): return {**scan_stats,"running":running,"market":market()}
@app.post("/api/scanner/start")
async def scanner_start():
    global running,scan_task
    if not secret_get("upstox_token"): raise HTTPException(409,"Connect Upstox first")
    running=True
    if not scan_task or scan_task.done(): scan_task=asyncio.create_task(runner())
    return {"running":True}
@app.post("/api/scanner/stop")
async def scanner_stop(): global running; running=False; return {"running":False}
@app.get("/api/signals")
async def signals(): return {"signals":rows("SELECT * FROM signals ORDER BY id DESC LIMIT 1000")}
@app.get("/api/signals/active")
async def active(): return {"signals":rows("SELECT * FROM signals WHERE status IN ('TRIGGERED','LIVE','TARGET_1','TARGET_2') ORDER BY id DESC")}
@app.get("/api/settings")
async def get_settings(): return settings()
@app.put("/api/settings")
async def set_settings(body:dict): putv("settings",{**settings(),**body}); return settings()
@app.get("/api/telegram/status")
async def tgstatus(): return {"configured":bool(secret_get("telegram_token") and secret_get("telegram_chat")),"bot_token":mask(secret_get("telegram_token")),"chat_id":mask(secret_get("telegram_chat"))}
@app.post("/api/telegram/config")
async def tgconfig(req:TelegramConfig): putv("telegram_token",req.bot_token); putv("telegram_chat",req.chat_id); return {"saved":True}
@app.post("/api/telegram/test")
async def tgtest():
    status=await telegram({"direction":"BUY","symbol":"TEST","breakout":100,"entry":100.1,"stop_loss":100,"t1":100.2,"t2":100.3,"t3":100.4,"score":40,"signal_time":now().strftime("%H:%M:%S")}); return {"status":status}
@app.get("/api/journal")
async def getjournal(): return {"entries":rows("SELECT * FROM journal ORDER BY id DESC")}
@app.post("/api/journal")
async def postjournal(j:Journal):
    c=conn(); c.execute("INSERT INTO journal(date,symbol,direction,entry,stop_loss,t1,t2,exit,result,pnl,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",tuple(j.model_dump().values())); c.commit(); c.close(); return {"saved":True}
@app.websocket("/ws/live")
async def ws(socket:WebSocket):
    await socket.accept()
    try:
        while True: await socket.send_json({"market":market(),"scanner":{**scan_stats,"running":running},"signals":rows("SELECT * FROM signals ORDER BY id DESC LIMIT 25")}); await asyncio.sleep(2)
    except WebSocketDisconnect: pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)