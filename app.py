import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from gemini_client import GeminiAssistant

load_dotenv()

app = Flask(__name__)
CORS(app)

START_TIME = time.time()
BOT_NAME = os.environ.get("BOT_NAME", "My Assistant")

try:
    assistant = GeminiAssistant()
    GEMINI_READY = True
    GEMINI_INIT_ERROR = None
except RuntimeError as exc:
    assistant = None
    GEMINI_READY = False
    GEMINI_INIT_ERROR = str(exc)

def _uptime_seconds() -> int:
    return int(time.time() - START_TIME)

def _human_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

@app.get("/")
def status_page():
    return render_template("index.html", bot_name=BOT_NAME)

@app.get("/api/health")
def health():
    uptime = _uptime_seconds()
    return jsonify({
        "status": "online" if GEMINI_READY else "degraded",
        "gemini_configured": GEMINI_READY,
        "gemini_error": GEMINI_INIT_ERROR,
        "model": assistant.model if assistant else None,
        "uptime_seconds": uptime,
        "uptime_human": _human_uptime(uptime),
        "active_conversations": assistant.active_conversation_count() if assistant else 0,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    })

@app.get("/api/info")
def info():
    return jsonify({
        "bot_name": BOT_NAME,
        "model": assistant.model if assistant else None,
        "endpoints": {
            "chat": "POST /api/chat  { message, user_id? }",
            "reset": "POST /api/reset  { user_id? }",
            "health": "GET /api/health",
        },
    })

@app.post("/api/chat")
def chat():
    if not GEMINI_READY:
        return jsonify({"error": "Gemini is not configured on the server", "detail": GEMINI_INIT_ERROR}), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    user_id = str(data.get("user_id") or "default_user")

    if not message:
        return jsonify({"error": "Field 'message' is required and cannot be empty"}), 400

    try:
        reply = assistant.chat(user_id=user_id, message=message)
    except RuntimeError as exc:
        return jsonify({"error": "Failed to get a response from Gemini", "detail": str(exc)}), 502

    return jsonify({
        "response": reply,
        "user_id": user_id,
        "model": assistant.model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

@app.post("/api/reset")
def reset():
    if not GEMINI_READY:
        return jsonify({"error": "Gemini is not configured"}), 503
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id") or "default_user")
    assistant.reset_history(user_id)
    return jsonify({"status": "ok", "user_id": user_id})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)