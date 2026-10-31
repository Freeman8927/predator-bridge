"""
================================================================================
Market Predator — Cloud Bridge (Render / FastAPI)
================================================================================
"""

import os
import uuid
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import uvicorn

# ==============================================================================
# CONFIG
# ==============================================================================
APP_VERSION = "2.5.0"
BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY", "")

app = FastAPI(title="Market Predator Cloud Bridge", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# PYDANTIC MODELS
# ==============================================================================
class ChartConfig(BaseModel):
    symbol: str = Field(default="XAUUSD", max_length=20)
    timeframe: str = Field(default="M5", pattern=r"^(M1|M5|M15|M30|H1|H4|D1)$")
    accountId: str = Field(default="MASTER", max_length=64)

class ChartUpdate(BaseModel):
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    accountId: Optional[str] = None
    candles: List[Dict[str, Any]] = Field(default_factory=list)
    visuals: Optional[Dict[str, Any]] = None

class HistoryRequest(BaseModel):
    symbol: str
    timeframe: str
    end_time: float

class HistoryResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: List[Dict[str, Any]] = Field(default_factory=list)

class ExecuteTrade(BaseModel):
    action: str = Field(pattern=r"^(BUY|SELL)$")
    symbol: str = Field(default="XAUUSD")
    lots: float = Field(default=0.01, gt=0, le=100)
    accountId: str = Field(default="MASTER")

class AlertCreate(BaseModel):
    id: Optional[str] = None
    symbol: str
    price: float
    condition: str = Field(pattern=r"^(above|below|crosses)$")
    note: str = Field(default="", max_length=500)

class FillEcho(BaseModel):
    alert_id: str = ""
    clientRef: str = ""
    ticket: int = 0
    deal: int = 0
    position_id: int = 0
    symbol: str
    side: str = Field(pattern=r"^(buy|sell)$")
    volume: float
    price: float
    filled_at: str
    status: str = Field(pattern=r"^(filled|partial|rejected)$")
    retcode: int = 0

class WebhookPayload(BaseModel):
    accountId: str
    brokerName: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    floatingPL: Optional[float] = None
    copierMode: Optional[str] = "STANDALONE"
    isLive: Optional[bool] = True
    bid: Optional[float] = None
    ask: Optional[float] = None
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    lastMessage: Optional[str] = ""         # <-- NEW
    lastMessageAt: Optional[float] = 0.0    # <-- NEW

# ==============================================================================
# IN-MEMORY STATE
# ==============================================================================
_state_lock = asyncio.Lock()

LIVE_DATA: Dict[str, Any] = {"accounts": {}, "timestamp": ""}
VPS_LAST_SEEN: str = ""

CHART_CONFIG: Dict[str, Any] = {"symbol": "XAUUSD", "timeframe": "M5", "accountId": "MASTER"}
CHART_DATA: Dict[str, Any] = {
    "symbol": "XAUUSD", "timeframe": "M5", "accountId": "MASTER",
    "candles": [], "visuals": {}, "updated_at": "",
}

ACTIVE_ALERTS: List[Dict[str, Any]] = []
PENDING_COMMANDS: List[Dict[str, Any]] = []
PENDING_HISTORY: Optional[Dict[str, Any]] = None
HISTORY_RESPONSE: List[Dict[str, Any]] = []
HISTORY_EXHAUSTED: bool = False

FILL_ECHOES: List[Dict[str, Any]] = []

# ==============================================================================
# RATE LIMITING & AUTH
# ==============================================================================
_rate_buckets: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 1.0
RATE_LIMIT_MAX = 10
RATE_LIMIT_MAX_BRIDGE = 60

async def rate_limit(request: Request, max_requests: int = RATE_LIMIT_MAX):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = _rate_buckets[ip]
    while bucket and bucket[0] < now - RATE_LIMIT_WINDOW:
        bucket.pop(0)
    if len(bucket) >= max_requests:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)

async def bridge_auth(request: Request):
    if not BRIDGE_API_KEY:
        return
    key = request.headers.get("X-Bridge-Key", "")
    if key != BRIDGE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid bridge key")

# ==============================================================================
# CHART ENDPOINTS
# ==============================================================================
@app.get("/api/chart/config")
async def get_chart_config(_: None = Depends(rate_limit)):
    return {**CHART_CONFIG, "cache_size": len(CHART_DATA.get("candles", []))}

@app.get("/api/chart_config", include_in_schema=False)
async def get_chart_config_legacy(_: None = Depends(rate_limit)):
    return await get_chart_config()

@app.put("/api/chart/config")
async def put_chart_config(cfg: ChartConfig, _: None = Depends(rate_limit)):
    async with _state_lock:
        if CHART_CONFIG["symbol"] != cfg.symbol or CHART_CONFIG["timeframe"] != cfg.timeframe:
            CHART_DATA["candles"] = []
            
        CHART_CONFIG.update(cfg.model_dump())
        CHART_DATA["symbol"] = CHART_CONFIG["symbol"]
        CHART_DATA["timeframe"] = CHART_CONFIG["timeframe"]
    return {"status": "ok", "config": CHART_CONFIG}

@app.post("/api/set_chart_config", include_in_schema=False)
async def set_chart_config_legacy(cfg: ChartConfig, _: None = Depends(rate_limit)):
    return await put_chart_config(cfg)

@app.patch("/api/chart/config")
async def patch_chart_config(update: ChartUpdate, _: None = Depends(rate_limit)):
    async with _state_lock:
        if update.symbol:
            CHART_DATA["symbol"] = update.symbol
        if update.timeframe:
            CHART_DATA["timeframe"] = update.timeframe
        if update.accountId:
            CHART_DATA["accountId"] = update.accountId

        if update.candles:
            if not CHART_DATA["candles"]:
                CHART_DATA["candles"] = update.candles
            else:
                for c in update.candles:
                    t = c.get("time")
                    if t is None:
                        continue
                    last = CHART_DATA["candles"][-1]
                    if t == last.get("time"):
                        CHART_DATA["candles"][-1] = c
                    elif t > last.get("time", 0):
                        CHART_DATA["candles"].append(c)
        if update.visuals is not None:
            CHART_DATA["visuals"] = update.visuals
        CHART_DATA["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": "ok"}

@app.post("/api/update_chart", include_in_schema=False)
async def update_chart_legacy(update: ChartUpdate, _: None = Depends(rate_limit)):
    return await patch_chart_config(update)

@app.get("/api/chart/data")
async def get_chart_data(symbol: str = "XAUUSD", _: None = Depends(rate_limit)):
    return {
        "status": "ok",
        "symbol": CHART_DATA.get("symbol", symbol),
        "timeframe": CHART_DATA.get("timeframe", "M5"),
        "accountId": CHART_DATA.get("accountId", "MASTER"),
        "candles": CHART_DATA.get("candles", []),
        "visuals": CHART_DATA.get("visuals", {}),
        "online": bool(CHART_DATA.get("candles")),
    }

@app.get("/api/chart_data", include_in_schema=False)
async def get_chart_data_legacy(symbol: str = "XAUUSD", _: None = Depends(rate_limit)):
    return await get_chart_data(symbol)

# ==============================================================================
# HISTORY
# ==============================================================================
@app.post("/api/request_history")
async def request_history(req: HistoryRequest, _: None = Depends(rate_limit)):
    global PENDING_HISTORY, HISTORY_RESPONSE, HISTORY_EXHAUSTED
    async with _state_lock:
        PENDING_HISTORY = req.model_dump()
        HISTORY_RESPONSE = []
        HISTORY_EXHAUSTED = False
    return {"status": "requested"}

@app.get("/api/pending_history")
async def get_pending_history(_: None = Depends(bridge_auth)):
    global PENDING_HISTORY
    req = PENDING_HISTORY
    PENDING_HISTORY = None
    return {"request": req}

@app.post("/api/history_response")
async def post_history_response(resp: HistoryResponse, _: None = Depends(bridge_auth)):
    global HISTORY_RESPONSE, HISTORY_EXHAUSTED
    async with _state_lock:
        HISTORY_RESPONSE = resp.candles
        HISTORY_EXHAUSTED = len(resp.candles) == 0
    return {"status": "ok"}

@app.get("/api/history_response")
async def get_history_response(_: None = Depends(rate_limit)):
    global HISTORY_RESPONSE, HISTORY_EXHAUSTED
    async with _state_lock:
        if HISTORY_EXHAUSTED:
            return JSONResponse(status_code=200, content={"status": "exhausted", "candles": []})
        if not HISTORY_RESPONSE:
            return JSONResponse(status_code=202, content={"status": "pending"})
        data = HISTORY_RESPONSE
        HISTORY_RESPONSE = []
        return {"status": "ok", "candles": data}

# ==============================================================================
# TELEMETRY / DATA
# ==============================================================================
@app.post("/api/webhook")
async def receive_data(payload: WebhookPayload, _: None = Depends(bridge_auth)):
    global VPS_LAST_SEEN, LIVE_DATA
    acc_id = payload.accountId
    async with _state_lock:
        VPS_LAST_SEEN = datetime.now(timezone.utc).isoformat()
        if acc_id != "heartbeat":
            LIVE_DATA["accounts"][acc_id] = payload.model_dump()
    return {"status": "ok"}

@app.get("/api/data")
async def get_data(_: None = Depends(rate_limit)):
    return {"status": "ok", "vps_last_seen": VPS_LAST_SEEN, **LIVE_DATA}

# ==============================================================================
# TRADING
# ==============================================================================
@app.post("/api/execute_trade")
async def execute_trade(trade: ExecuteTrade, _: None = Depends(rate_limit)):
    global PENDING_COMMANDS
    async with _state_lock:
        trade_cmd = {
            "id": f"trade_{uuid.uuid4().hex[:8]}",
            **trade.model_dump(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        PENDING_COMMANDS.append(trade_cmd)
    return {"status": "queued", "trade": trade_cmd}

@app.get("/api/pending_trade")
async def get_pending_trade(_: None = Depends(bridge_auth)):
    global PENDING_COMMANDS
    async with _state_lock:
        trade = next((c for c in PENDING_COMMANDS if c.get("action") in ("BUY", "SELL")), None)
        if trade:
            PENDING_COMMANDS.remove(trade)
    return {"trade": trade}

# ==============================================================================
# ALERTS
# ==============================================================================
@app.post("/api/alerts")
async def create_alert(alert: AlertCreate, _: None = Depends(rate_limit)):
    global ACTIVE_ALERTS
    async with _state_lock:
        new_alert = {
            "id": str(uuid.uuid4()),
            "clientRef": alert.id,
            "symbol": alert.symbol.upper(),
            "price": float(alert.price),
            "condition": alert.condition,
            "note": alert.note,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ACTIVE_ALERTS = [a for a in ACTIVE_ALERTS if a["id"] != new_alert["id"]]
        ACTIVE_ALERTS.append(new_alert)
    return {"status": "ok", "alert": new_alert}

@app.get("/api/alerts")
async def get_alerts(_: None = Depends(rate_limit)):
    return {"alerts": ACTIVE_ALERTS}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str, _: None = Depends(bridge_auth)):
    global ACTIVE_ALERTS
    async with _state_lock:
        ACTIVE_ALERTS = [a for a in ACTIVE_ALERTS if a["id"] != alert_id]
    return {"status": "deleted"}

# ==============================================================================
# FILL ECHO
# ==============================================================================
@app.post("/api/fill")
async def fill_echo(fill: FillEcho, _: None = Depends(bridge_auth)):
    global FILL_ECHOES
    async with _state_lock:
        FILL_ECHOES.append(fill.model_dump())
        if len(FILL_ECHOES) > 100:
            FILL_ECHOES = FILL_ECHOES[-100:]
    return {"status": "ok"}

@app.get("/api/fills")
async def get_fills(_: None = Depends(rate_limit)):
    return {"fills": FILL_ECHOES}

# ==============================================================================
# HEALTH
# ==============================================================================
@app.get("/ping")
def health_check():
    return {"status": "running", "version": APP_VERSION}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
