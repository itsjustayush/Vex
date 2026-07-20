import os
import time
from datetime import datetime, timezone
from functools import wraps
import jwt
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from gemini_client import GeminiAssistant

load_dotenv()

app = Flask(__name__)
CORS(app)

import uuid

# Temporary In-Memory Database for Notes until we connect Supabase Postgres
MOCK_DB = {
    "notes": [] 
}

START_TIME = time.time()
BOT_NAME = os.environ.get("BOT_NAME", "Vex")

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


def token_required(f):
    """
    This decorator protects endpoints. It checks for a valid JWT token
    issued by Supabase in the Authorization header.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split()
            if len(parts) == 2 and parts[0] == "Bearer":
                token = parts[1]
        
        if not token:
            return jsonify({"error": "Authentication Token is missing. Please log in."}), 401
        
        try:
            secret = os.environ.get("SUPABASE_JWT_SECRET", "")
            data = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
            current_user_id = data.get("sub") 
        except Exception as e:
            return jsonify({"error": "Token is invalid or expired", "detail": str(e)}), 401
            
        return f(current_user_id, *args, **kwargs)
    return decorated


@app.route("/")
def landing_page():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard_page():
    return render_template(
        "dashboard.html",
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", "")
    )

@app.route("/docs")
def docs_page():
    return render_template("docs.html")

@app.route("/status")
def status_page():
    return render_template("status.html")

@app.route("/login")
def login_page():
    return render_template(
        "login.html",
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", "")
    )

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


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

@app.get("/api/me")
@token_required
def get_current_user(current_user_id):
    """Test endpoint to verify valid JWT tokens."""
    return jsonify({
        "status": "success",
        "message": "You are securely authenticated!",
        "user_id": current_user_id
    })


# ==========================================
# REST API: NOTES (CRUD)
# ==========================================

@app.route("/api/v1/notes", methods=["GET", "POST"])
@token_required
def handle_notes(current_user_id):
    if request.method == "GET":
        # Fetch all notes for this user
        user_notes = [n for n in MOCK_DB["notes"] if n["user_id"] == current_user_id]
        return jsonify({"status": "success", "notes": user_notes}), 200

    if request.method == "POST":
        # Create a new note
        data = request.get_json() or {}
        new_note = {
            "id": f"nt_{uuid.uuid4().hex[:10]}",
            "user_id": current_user_id,
            "title": data.get("title", "Untitled Note"),
            "content": data.get("content", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tags": data.get("tags", [])
        }
        MOCK_DB["notes"].append(new_note)
        return jsonify({"status": "created", "note": new_note}), 201


@app.route("/api/v1/notes/<note_id>", methods=["DELETE"])
@token_required
def delete_note(current_user_id, note_id):
    # Find and delete the note
    global MOCK_DB
    initial_length = len(MOCK_DB["notes"])
    MOCK_DB["notes"] = [n for n in MOCK_DB["notes"] if not (n["id"] == note_id and n["user_id"] == current_user_id)]
    
    if len(MOCK_DB["notes"]) < initial_length:
        return jsonify({"status": "deleted"}), 200
    return jsonify({"error": "Note not found or unauthorized"}), 404


# ==========================================
# REST API: GOOGLE WORKSPACE
# ==========================================

@app.route("/api/v1/workspace/calendar", methods=["GET"])
@token_required
def get_calendar(current_user_id):
    """
    In the future, we will take the Google Provider Token from the user's session
    and hit the Google Calendar API here. For now, we return placeholder AI context.
    """
    return jsonify({
        "sync_status": "active",
        "provider": "google",
        "events": [
            {
                "event_id": "gcal_mock_1",
                "title": "Product Sync with Vex Team",
                "start_time": datetime.now(timezone.utc).isoformat(),
                "ai_context": "This meeting is related to your 'Project Alpha' note."
            }
        ]
    }), 200

@app.route("/settings")
def settings_page():
    return render_template(
        "settings.html",
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", "")
    )

@app.post("/api/chat")
def chat():
    if not GEMINI_READY:
        return jsonify({"error": "Gemini is not configured on the server", "detail": GEMINI_INIT_ERROR}), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    user_id = str(data.get("user_id") or "default_user")
    image_base64 = data.get("image_base64")
    dynamic_model = data.get("model")

    if not message and not image_base64:
        return jsonify({"error": "Field 'message' or 'image_base64' is required"}), 400

    try:
        reply = assistant.chat(
            user_id=user_id, 
            message=message, 
            image_base64=image_base64,
            dynamic_model=dynamic_model
        )
    except RuntimeError as exc:
        return jsonify({"error": "Failed to get a response from Gemini", "detail": str(exc)}), 502

    return jsonify({
        "response": reply,
        "user_id": user_id,
        "model": dynamic_model or assistant.model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)