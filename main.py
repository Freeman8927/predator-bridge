"""
================================================================================
Market Predator — Render Cloud Bridge (FastAPI)
================================================================================
"""
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

# NEW: Global state to store the user's chart selection
CHART_CONFIG = {
    "symbol": "XAUUSD",
    "timeframe": "M5",
    "accountId": "MASTER"
}

CHART_DATA = {
    "symbol": "XAUUSD",
    "timeframe": "M5",
    "candles": [],
    "visuals": {},
    "updated_at": ""
}

# ==============================================================================
# CHART CONFIGURATION (New)
# ==============================================================================
@app.post("/api/set_chart_config")
async def set_chart_config(request: Request):
    """Called by the Web App when the user changes symbol, timeframe, or account."""
    global CHART_CONFIG
    try:
        data = await request.json()
        CHART_CONFIG["symbol"] = data.get("symbol", "XAUUSD")
        CHART_CONFIG["timeframe"] = data.get("timeframe", "M5")
        CHART_CONFIG["accountId"] = data.get("accountId", "MASTER")
        
        print(f"📥 [RENDER] Updated Chart Config -> {CHART_CONFIG['symbol']} {CHART_CONFIG['timeframe']} (Acc: {CHART_CONFIG['accountId']})")
        
        return {"status": "ok", "config": CHART_CONFIG}
    except Exception as e:
        print(f"❌ [RENDER ERROR] Failed to set config: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/chart_config")
async def get_chart_config():
    """Called by the VPS Python Bridge to know what data to fetch."""
    return CHART_CONFIG

# ==============================================================================
# TELEMETRY & CHART DATA
# ==============================================================================
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
        LIVE_DATA["timestamp"] = datetime.utcnow().isoformat()
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
    return {"status": "ok"}

@app.get("/api/data")
async def get_data():
    return {"status": "ok", "vps_last_seen": VPS_LAST_SEEN, **LIVE_DATA}

@app.post("/api/update_chart")
@app.post("/api/update_visuals")
async def update_chart(request: Request):
    global CHART_DATA
    try:
        data = await request.json()
        if data:
            if "symbol" in data:
                CHART_DATA["symbol"] = data["symbol"]
            if "timeframe" in data:
                CHART_DATA["timeframe"] = data["timeframe"]
            if "candles" in data and isinstance(data["candles"], list):
                CHART_DATA["candles"] = data["candles"]
            if "visuals" in data and isinstance(data["visuals"], dict):
                CHART_DATA["visuals"] = data["visuals"]
            elif "trendline" in data:
                CHART_DATA["visuals"]["trendline"] = {
                    "level": data.get("level", 0.0),
                    "type": data.get("type", "NONE"),
                    "color": "#10b981" if data.get("type") == "BULLISH" else "#a855f7"
                }
            CHART_DATA["updated_at"] = datetime.utcnow().isoformat()
        return {"status": "ok", "candles_count": len(CHART_DATA["candles"])}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/chart_data")
async def get_chart_data(symbol: str = "XAUUSD"):
    return {
        "status": "ok",
        "symbol": CHART_DATA.get("symbol", symbol),
        "timeframe": CHART_DATA.get("timeframe", "M5"), # Added timeframe to response
        "candles": CHART_DATA.get("candles", []),
        "visuals": CHART_DATA.get("visuals", {}),
        "updated_at": CHART_DATA.get("updated_at", ""),
        "online": bool(CHART_DATA.get("candles"))
    }

# ==============================================================================
# TRADE EXECUTION
# ==============================================================================
@app.post("/api/execute_trade")
async def execute_trade(request: Request):
    global PENDING_COMMANDS
    try:
        data = await request.json()
        trade_cmd = {
            "id": f"trade_{uuid.uuid4().hex[:8]}",
            "action": data.get("action", "BUY").upper(),
            "symbol": data.get("symbol", "XAUUSD").upper(),
            "lots": float(data.get("lots", 0.01)),
            "timestamp": data.get("timestamp", datetime.utcnow().isoformat())
        }
        PENDING_COMMANDS.append(trade_cmd)
        return {"status": "queued", "trade": trade_cmd}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/pending_trade")
async def get_pending_trade():
    global PENDING_COMMANDS
    trade = None
    for i, cmd in enumerate(PENDING_COMMANDS):
        if isinstance(cmd, dict) and cmd.get("action") in ("BUY", "SELL", "QUICK_BUY", "QUICK_SELL"):
            trade = PENDING_COMMANDS.pop(i)
            break
    return {"trade": trade}

# ==============================================================================
# ALERTS & COMMANDS
# ==============================================================================
@app.post("/api/alerts")
async def create_alert(request: Request):
    data = await request.json()
    if data and "symbol" in data and "price" in data and "condition" in data:
        new_alert = {
            "id": str(uuid.uuid4()),
            "symbol": data["symbol"].upper(),
            "price": float(data["price"]),
            "condition": data["condition"],
            "note": data.get("note", ""),
            "created_at": datetime.utcnow().isoformat()
        }
        ACTIVE_ALERTS.append(new_alert)
        return {"status": "ok", "alert": new_alert}
    return {"status": "error", "message": "Invalid payload"}

@app.get("/api/alerts")
async def get_alerts():
    return {"alerts": ACTIVE_ALERTS}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    global ACTIVE_ALERTS
    ACTIVE_ALERTS = [a for a in ACTIVE_ALERTS if a["id"] != alert_id]
    return {"status": "deleted"}

@app.post("/api/command")
async def send_command(request: Request):
    data = await request.json()
    if data and "command" in data:
        PENDING_COMMANDS.append(data["command"])
    return {"status": "queued"}

@app.get("/api/commands")
async def get_commands():
    global PENDING_COMMANDS
    cmds = PENDING_COMMANDS.copy()
    PENDING_COMMANDS.clear()
    return {"commands": cmds}

@app.get("/ping")
@app.get("/health")
@app.get("/")
def health_check():
    return {
        "status": "running",
        "service": "Market Predator Cloud Bridge",
        "vps_last_seen": VPS_LAST_SEEN,
        "candles_cached": len(CHART_DATA.get("candles", []))
    }
