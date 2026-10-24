@app.post("/api/webhook")
async def receive_data(request: Request):
    global LIVE_DATA, VPS_LAST_SEEN
    data = await request.json()
    account_id = str(data.get("accountId"))
    
    if account_id == "heartbeat":
        # Update handshake but do NOT save to accounts list
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
        return {"status": "ok"}
    
    if account_id:
        LIVE_DATA["accounts"][account_id] = data
        LIVE_DATA["timestamp"] = datetime.utcnow().isoformat()
        VPS_LAST_SEEN = datetime.utcnow().isoformat()
        
    return {"status": "ok"}
