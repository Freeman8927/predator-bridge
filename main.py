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

# --- HISTORY SCROLL STATE ---
PENDING_HISTORY = None
HISTORY_RESPONSE = []

# ==============================================================================
# CHART CONFIGURATION & HISTORY
# ==============================================================================
@app.post("/api/set_chart_config")
async def set_chart_config(request: Request):
    global CHART_CONFIG
    try:
        data = await request.json()
        CHART_CONFIG["symbol"] = data.get("symbol", "XAUUSD")
        CHART_CONFIG["timeframe"] = data.get("timeframe", "M5")
        CHART_CONFIG["accountId"] = data.get("accountId", "MASTER")
        return {"status": "ok", "config": CHART_CONFIG}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/chart_config")
async def get_chart_config():
    return CHART_CONFIG

@app.post("/api/request_history")
async def request_history(request: Request):
    global PENDING_HISTORY, HISTORY_RESPONSE
    data = await request.json()
    PENDING_HISTORY = data
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
    data = await request.json()
    HISTORY_RESPONSE = data.get("candles", [])
    return {"status": "ok"}

@app.get("/api/history_response")
async def get_history_response():
    global HISTORY_RESPONSE
    data = HISTORY_RESPONSE
    HISTORY_RESPONSE = []
    return {"candles": data}

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
async def update_chart(request: Request):
    global CHART_DATA
    try:
        data = await request.json()
        if data:
            if "symbol" in data: CHART_DATA["symbol"] = data["symbol"]
            if "timeframe" in data: CHART_DATA["timeframe"] = data["timeframe"]
            if "candles" in data and isinstance(data["candles"], list): CHART_DATA["candles"] = data["candles"]
            if "visuals" in data: CHART_DATA["visuals"] = data["visuals"]
            CHART_DATA["updated_at"] = datetime.utcnow().isoformat()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/chart_data")
async def get_chart_data(symbol: str = "XAUUSD"):
    return {
        "status": "ok",
        "symbol": CHART_DATA.get("symbol", symbol),
        "timeframe": CHART_DATA.get("timeframe", "M5"),
        "candles": CHART_DATA.get("candles", []),
        "visuals": CHART_DATA.get("visuals", {}),
        "online": bool(CHART_DATA.get("candles"))
    }

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
    return {"status": "running", "candles_cached": len(CHART_DATA.get("candles", []))}
