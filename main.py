from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uuid

app = FastAPI(title="Market Predator Cloud Bridge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

LIVE_DATA = {"accounts": {}, "timestamp": ""}
ACTIVE_ALERTS = []
PENDING_COMMANDS = []
VPS_LAST_SEEN = ""

CHART_CONFIG = {"symbol": "XAUUSD", "timeframe": "M5", "accountId": "MASTER"}
CHART_DATA = {"symbol": "XAUUSD", "timeframe": "M5", "accountId": "MASTER", "candles": [], "visuals": {}, "updated_at": ""}

# Local Cache to store candles per symbol_timeframe
CANDLE_CACHE = {}

PENDING_HISTORY = None
HISTORY_RESPONSE = []

@app.post("/api/set_chart_config")
async def set_chart_config(request: Request):
    global CHART_CONFIG, CHART_DATA
    data = await request.json()
    
    CHART_CONFIG["symbol"] = data.get("symbol", "XAUUSD")
    CHART_CONFIG["timeframe"] = data.get("timeframe", "M5")
    CHART_CONFIG["accountId"] = data.get("accountId", "MASTER")
    
    # Check if React has cached this timeframe. If yes, load from Render's cache.
    cache_key = f"{CHART_CONFIG['symbol']}_{CHART_CONFIG['timeframe']}"
    if cache_key in CANDLE_CACHE and len(CANDLE_CACHE[cache_key]) > 0:
        CHART_DATA["candles"] = CANDLE_CACHE[cache_key]
    else:
        CHART_DATA["candles"] = []
        
    CHART_DATA["timeframe"] = CHART_CONFIG["timeframe"]
    CHART_DATA["symbol"] = CHART_CONFIG["symbol"]
    
    return {"status": "ok", "config": CHART_CONFIG}

# THE FIX IS HERE: Dynamically calculate the cache size based on actual data held
@app.get("/api/chart_config")
async def get_chart_config(): 
    return {**CHART_CONFIG, "cache_size": len(CHART_DATA.get("candles", []))}

@app.post("/api/update_chart")
async def update_chart(request: Request):
    global CHART_DATA, CANDLE_CACHE
    data = await request.json()
    
    if data:
        if "symbol" in data: CHART_DATA["symbol"] = data["symbol"]
        if "timeframe" in data: CHART_DATA["timeframe"] = data["timeframe"]
        if "accountId" in data: CHART_DATA["accountId"] = data["accountId"]
        
        incoming_candles = data.get("candles", [])
        if incoming_candles:
            if not CHART_DATA["candles"]:
                CHART_DATA["candles"] = incoming_candles
            else:
                for c in incoming_candles:
                    if c["time"] == CHART_DATA["candles"][-1]["time"]:
                        CHART_DATA["candles"][-1] = c # Update live candle
                    elif c["time"] > CHART_DATA["candles"][-1]["time"]:
                        CHART_DATA["candles"].append(c) # Append new candle
            
            # Save to cache
            cache_key = f"{CHART_DATA['symbol']}_{CHART_DATA['timeframe']}"
            CANDLE_CACHE[cache_key] = CHART_DATA["candles"]
            
        CHART_DATA["updated_at"] = datetime.utcnow().isoformat()
    return {"status": "ok"}

@app.post("/api/request_history")
async def request_history(request: Request):
    global PENDING_HISTORY, HISTORY_RESPONSE
    PENDING_HISTORY = await request.json()
    HISTORY_RESPONSE = []
    return {"status": "requested"}

@app.get("/api/pending_history")
async def get_pending_history():
    global PENDING_HISTORY
    req = PENDING_HISTORY
    PENDING_HISTORY = None
    return {"request": req}

@app.post("/api/history_response")
async def history_response(request: Request):
    global HISTORY_RESPONSE
    HISTORY_RESPONSE = (await request.json()).get("candles", [])
    return {"status": "ok"}

@app.get("/api/history_response")
async def get_history_response():
    global HISTORY_RESPONSE
    data = HISTORY_RESPONSE
    HISTORY_RESPONSE = []
    return {"candles": data}

@app.post("/api/webhook")
async def receive_data(request: Request):
    global LIVE_DATA, VPS_LAST_SEEN
    data = await request.json()
    acc_id = str(data.get("accountId"))
    if acc_id == "heartbeat": VPS_LAST_SEEN = datetime.utcnow().isoformat()
    elif acc_id:
        LIVE_DATA["accounts"][acc_id] = data
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
    return {"status": "ok"}

@app.get("/api/data")
async def get_data(): return {"status": "ok", "vps_last_seen": VPS_LAST_SEEN, **LIVE_DATA}

@app.get("/api/chart_data")
async def get_chart_data(symbol: str = "XAUUSD"):
    return {"status": "ok", "symbol": CHART_DATA.get("symbol", symbol), "timeframe": CHART_DATA.get("timeframe", "M5"), "accountId": CHART_DATA.get("accountId", "MASTER"), "candles": CHART_DATA.get("candles", []), "visuals": CHART_DATA.get("visuals", {}), "online": bool(CHART_DATA.get("candles"))}

@app.post("/api/execute_trade")
async def execute_trade(request: Request):
    global PENDING_COMMANDS
    data = await request.json()
    trade_cmd = {"id": f"trade_{uuid.uuid4().hex[:8]}", "action": data.get("action", "BUY").upper(), "symbol": data.get("symbol", "XAUUSD").upper(), "lots": float(data.get("lots", 0.01)), "accountId": data.get("accountId", "MASTER"), "timestamp": datetime.utcnow().isoformat()}
    PENDING_COMMANDS.append(trade_cmd)
    return {"status": "queued", "trade": trade_cmd}

@app.get("/api/pending_trade")
async def get_pending_trade():
    global PENDING_COMMANDS
    trade = next((cmd for cmd in PENDING_COMMANDS if isinstance(cmd, dict) and cmd.get("action") in ("BUY", "SELL")), None)
    if trade: PENDING_COMMANDS.remove(trade)
    return {"trade": trade}

@app.post("/api/alerts")
async def create_alert(request: Request):
    data = await request.json()
    if data:
        new_alert = {"id": str(uuid.uuid4()), "symbol": data["symbol"].upper(), "price": float(data["price"]), "condition": data["condition"], "note": data.get("note", ""), "created_at": datetime.utcnow().isoformat()}
        ACTIVE_ALERTS.append(new_alert)
        return {"status": "ok", "alert": new_alert}
    return {"status": "error"}

@app.get("/api/alerts")
async def get_alerts(): return {"alerts": ACTIVE_ALERTS}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    global ACTIVE_ALERTS
    ACTIVE_ALERTS = [a for a in ACTIVE_ALERTS if a["id"] != alert_id]
    return {"status": "deleted"}

@app.get("/ping")
def health_check(): return {"status": "running"}
