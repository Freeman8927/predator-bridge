@app.post("/api/alerts")
async def create_alert(request: Request):
    global ACTIVE_ALERTS
    data = await request.json()
    if data:
        new_alert = {
            "id": data.get("id", str(uuid.uuid4())), # Accept the ID from React
            "symbol": data["symbol"].upper(),
            "price": float(data["price"]),
            "condition": data["condition"],
            "note": data.get("note", ""),
            "created_at": datetime.utcnow().isoformat()
        }
        # Remove any existing alert with the same ID
        ACTIVE_ALERTS = [a for a in ACTIVE_ALERTS if a["id"] != new_alert["id"]]
        ACTIVE_ALERTS.append(new_alert)
        return {"status": "ok", "alert": new_alert}
    return {"status": "error", "message": "Invalid payload"}
