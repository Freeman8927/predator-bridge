from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uuid

app = FastAPI(title="Market Predator Cloud Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LIVE_DATA = {"accounts": {}, "timestamp": ""}
ACTIVE_ALERTS = []
PENDING_COMMANDS = []
VPS_LAST_SEEN = ""

# The config stores what the user selected on the web app
CHART_CONFIG = {
    "symbol": "XAUUSD",
    "timeframe": "M5",
    "accountId": "MASTER"
}

CHART_DATA = {
    "symbol": "XAUUSD",
    "timeframe": "M5", # Added timeframe
    "candles": [],
    "visuals": {},
    "updated_at": ""
}

# 1. The VPS polls this to know what to fetch
@app.get("/api/chart_config")
async def get_chart_config():
    return CHART_CONFIG

# 2. The Web App posts this when you change the dropdown
@app.post("/api/set_chart_config")
async def set_chart_config(request: Request):
    global CHART_CONFIG
    try:
        data = await request.json()
        CHART_CONFIG["symbol"] = data.get("symbol", "XAUUSD")
        CHART_CONFIG["timeframe"] = data.get("timeframe", "M5")
        CHART_CONFIG["accountId"] = data.get("accountId", "MASTER")
        print(f"📥 [RENDER] Updated Config -> {CHART_CONFIG}")
        return {"status": "ok", "config": CHART_CONFIG}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 3. The VPS pushes data here
@app.post("/api/update_chart")
async def update_chart(request: Request):
    global CHART_DATA
    try:
        data = await request.json()
        if "symbol" in data: CHART_DATA["symbol"] = data["symbol"]
        if "timeframe" in data: CHART_DATA["timeframe"] = data["timeframe"]
        if "candles" in data and isinstance(data["candles"], list):
            CHART_DATA["candles"] = data["candles"]
        if "visuals" in data: CHART_DATA["visuals"] = data["visuals"]
        CHART_DATA["updated_at"] = datetime.utcnow().isoformat()
        return {"status": "ok", "candles_count": len(CHART_DATA["candles"])}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 4. The Web App fetches data here
@app.get("/api/chart_data")
async def get_chart_data():
    return {
        "status": "ok",
        "symbol": CHART_DATA.get("symbol", "XAUUSD"),
        "timeframe": CHART_DATA.get("timeframe", "M5"),
        "candles": CHART_DATA.get("candles", []),
        "visuals": CHART_DATA.get("visuals", {}),
        "online": bool(CHART_DATA.get("candles"))
    }

# Remaining endpoints (Telemetry, Trade, Alerts)
@app.post("/api/webhook")
async def receive_data(request: Request):
    global LIVE_DATA, VPS_LAST_SEEN
    data = await request.json()
    account_id = str(data.get("accountId"))
    if account_id == "heartbeat":
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
        return {"status": "ok"}
    if account_id:
        LIVE_DATA["accounts"][account_id] = data
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
    return {"status": "ok"}

@app.get("/api/data")
async def get_data():
    return {"status": "ok", "vps_last_seen": VPS_LAST_SEEN, **LIVE_DATA}

@app.post("/api/execute_trade")
async def execute_trade(request: Request):
    global PENDING_COMMANDS
    data = await request.json()
    trade_cmd = {
        "id": f"trade_{uuid.uuid4().hex[:8]}",
        "action": data.get("action", "BUY").upper(),
        "symbol": data.get("symbol", "XAUUSD").upper(),
        "lots": float(data.get("lots", 0.01)),
        "timestamp": datetime.utcnow().isoformat()
    }
    PENDING_COMMANDS.append(trade_cmd)
    return {"status": "queued", "trade": trade_cmd}

@app.get("/api/pending_trade")
async def get_pending_trade():
    global PENDING_COMMANDS
    trade = None
    for i, cmd in enumerate(PENDING_COMMANDS):
        if isinstance(cmd, dict) and cmd.get("action") in ("BUY", "SELL", "QUICK_BUY", "QUICK_SELL"):
            trade = PENDING_COMMANDS.pop(i)
            break
    return {"trade": trade}

@app.get("/ping")
@app.get("/health")
@app.get("/")
def health_check():
    return {"status": "running", "candles_cached": len(CHART_DATA.get("candles", []))}
