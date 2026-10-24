from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LIVE_DATA = {"accounts": {}, "timestamp": ""}
ACTIVE_ALERTS = []
PENDING_COMMANDS = []
VPS_LAST_SEEN = ""

@app.post("/api/webhook")
async def receive_data(request: Request):
    global LIVE_DATA, VPS_LAST_SEEN
    data = await request.json()
    account_id = str(data.get("accountId"))
    
    # Ignore heartbeat pings from showing up as real accounts
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

@app.get("/")
def health_check():
    return {"status": "running", "service": "FastAPI Bridge"}
