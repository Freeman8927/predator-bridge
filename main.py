from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

app = FastAPI()

# Allow your web app to fetch this data
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# This holds the live data in memory
LIVE_DATA = {"accounts": {}, "timestamp": ""}

@app.post("/api/webhook")
async def receive_data(request: Request):
    global LIVE_DATA
    data = await request.json()
    account_id = str(data.get("accountId"))
    
    if account_id:
        LIVE_DATA["accounts"][account_id] = data
        LIVE_DATA["timestamp"] = datetime.utcnow().isoformat()
        
    return {"status": "ok"}

@app.get("/api/data")
async def get_data():
    return {"status": "ok", **LIVE_DATA}

@app.get("/")
def health_check():
    return {"status": "running", "service": "FastAPI Bridge"}