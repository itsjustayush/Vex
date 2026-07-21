
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from dotenv import load_dotenv
import os
import time
import uuid
from datetime import datetime, timezone
import jwt
import httpx

# -------- Setup --------
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") # For server-side operations
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-key") # Replace with a strong secret key
START_TIME = time.time()

# --- Supabase Client (using httpx for direct API calls) ---
def get_supabase_headers(jwt_token=None):
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    return headers

# ==========================================
# AUTHENTICATION GUARD
# ==========================================

def get_current_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None # Or raise HTTPException for API routes
    token = auth_header.split(" ", 1)[1]
    try:
        # In a real app, you'd verify the token with Supabase's public key
        # For now, we'll just decode to get the user_id
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_signature": False}) # Verify signature in production
        user_id = payload.get("sub")
        return user_id
    except Exception as e:
        print(f"Token validation error: {e}")
        return None

# ==========================================
# FRONTEND TEMPLATE ROUTES
# ==========================================

@app.route("/")
def index_page():
    return render_template("index.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/login")
def login_page():
    return render_template("login.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/settings")
def settings_page():
    return render_template("settings.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/docs")
def docs_page():
    return render_template("docs.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/status")
def status_page():
    return render_template("status.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/auth/callback")
def callback_page():
    return render_template("callback.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

# ==========================================
# CRUD API ROUTES (Supabase Integration)
# ==========================================

def _now() -> str: return datetime.now(timezone.utc).isoformat()

@app.route("/api/health")
def health():
    return jsonify({"status": "online", "uptime_seconds": int(time.time() - START_TIME)})

@app.route("/api/v1/projects", methods=["GET", "POST"])
def projects_api():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    if request.method == "GET":
        try:
            resp = httpx.get(f"{SUPABASE_URL}/rest/v1/projects",
                             headers=get_supabase_headers(request.headers.get("Authorization")), # Pass JWT from client
                             params={"user_id": f"eq.{user_id}"})
            resp.raise_for_status()
            return jsonify({"projects": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

    elif request.method == "POST":
        data = request.get_json()
        title = data.get("title", "").strip() or "Untitled Project"
        description = data.get("description", "").strip()
        new_proj = {"id": f"prj_{uuid.uuid4().hex[:12]}", "user_id": user_id, "title": title, "description": description, "created_at": _now()}
        try:
            resp = httpx.post(f"{SUPABASE_URL}/rest/v1/projects",
                              headers=get_supabase_headers(request.headers.get("Authorization")), # Pass JWT from client
                              json=new_proj)
            resp.raise_for_status()
            return jsonify({"project": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/v1/projects/<project_id>", methods=["DELETE"])
def delete_project_api(project_id):
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    try:
        # Delete project
        resp = httpx.delete(f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&user_id=eq.{user_id}",
                            headers=get_supabase_headers(request.headers.get("Authorization")))
        resp.raise_for_status()
        
        # Delete associated files
        resp = httpx.delete(f"{SUPABASE_URL}/rest/v1/files?project_id=eq.{project_id}",
                            headers=get_supabase_headers(request.headers.get("Authorization")))
        resp.raise_for_status()

        return jsonify({"status": "deleted"})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/v1/projects/<project_id>/files", methods=["GET", "POST"])
def files_api(project_id):
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    if request.method == "GET":
        try:
            resp = httpx.get(f"{SUPABASE_URL}/rest/v1/files",
                             headers=get_supabase_headers(request.headers.get("Authorization")), # Pass JWT from client
                             params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"})
            resp.raise_for_status()
            return jsonify({"files": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

    elif request.method == "POST":
        data = request.get_json()
        new_file = {
            "id": f"nt_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "project_id": project_id,
            "title": data.get("title", "Untitled Note"),
            "content": data.get("content", ""),
            "folder": data.get("folder", "General"),
            "extension": data.get("extension", "md"),
            "created_at": _now(),
            "updated_at": _now()
        }
        try:
            resp = httpx.post(f"{SUPABASE_URL}/rest/v1/files",
                              headers=get_supabase_headers(request.headers.get("Authorization")), # Pass JWT from client
                              json=new_file)
            resp.raise_for_status()
            return jsonify({"file": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/v1/projects/<project_id>/files/<file_id>", methods=["PUT", "DELETE"])
def file_detail_api(project_id, file_id):
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    if request.method == "PUT":
        data = request.get_json()
        patch_data = {"updated_at": _now()}
        if "title" in data: patch_data["title"] = data["title"]
        if "content" in data: patch_data["content"] = data["content"]
        if "folder" in data: patch_data["folder"] = data["folder"]
        if "extension" in data: patch_data["extension"] = data["extension"]

        try:
            resp = httpx.patch(f"{SUPABASE_URL}/rest/v1/files?id=eq.{file_id}&project_id=eq.{project_id}&user_id=eq.{user_id}",
                               headers=get_supabase_headers(request.headers.get("Authorization")), # Pass JWT from client
                               json=patch_data)
            resp.raise_for_status()
            if resp.json():
                return jsonify({"file": resp.json()[0]})
            return jsonify({"detail": "File not found"}), 404
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

    elif request.method == "DELETE":
        try:
            resp = httpx.delete(f"{SUPABASE_URL}/rest/v1/files?id=eq.{file_id}&project_id=eq.{project_id}&user_id=eq.{user_id}",
                                headers=get_supabase_headers(request.headers.get("Authorization")))
            resp.raise_for_status()
            return jsonify({"status": "deleted"})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/v1/workspace/calendar", methods=["GET"])
def google_calendar():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    x_google_token = request.headers.get("X-Google-Token")
    if not x_google_token: return jsonify({"sync_status": "unlinked", "events": []})
    
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin={_now()}&maxResults=20&singleEvents=true&orderBy=startTime"
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {x_google_token}"}, timeout=10)
        resp.raise_for_status()
        events = [{"title": i.get("summary", "Event"), "start_time": i.get("start", {}).get("dateTime"), "description": i.get("description", "")} for i in resp.json().get("items", [])]
        return jsonify({"sync_status": "active", "events": events})
    except httpx.HTTPStatusError as e:
        return jsonify({"sync_status": "error", "detail": f"Google API error: {e.response.text}", "events": []}), e.response.status_code
    except httpx.RequestError as e:
        return jsonify({"sync_status": "error", "detail": f"Network error: {e}", "events": []}), 500

@app.route("/api/chat", methods=["POST"])
def chat():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401
    
    data = request.get_json()
    message = data.get("message", "")
    conversation_id = data.get("conversation_id", f"conv_{uuid.uuid4().hex[:12]}")
    
    # Store chat message in Supabase
    chat_msg = {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "conversation_id": conversation_id,
        "role": "user",
        "content": message,
        "created_at": _now()
    }
    
    try:
        # Save user message
        httpx.post(f"{SUPABASE_URL}/rest/v1/chat_messages",
                   headers=get_supabase_headers(request.headers.get("Authorization")),
                   json=chat_msg)
        
        # Call OpenAI API for AI response
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            ai_resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": message}],
                    "temperature": 0.7,
                    "max_tokens": 500
                },
                timeout=30
            )
            ai_resp.raise_for_status()
            ai_content = ai_resp.json()["choices"][0]["message"]["content"]
        else:
            ai_content = "AI assistant is not configured. Please set OPENAI_API_KEY."
        
        # Save AI response
        ai_msg = {
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": ai_content,
            "created_at": _now()
        }
        httpx.post(f"{SUPABASE_URL}/rest/v1/chat_messages",
                   headers=get_supabase_headers(request.headers.get("Authorization")),
                   json=ai_msg)
        
        return jsonify({"response": ai_content, "conversation_id": conversation_id})
    except Exception as e:
        return jsonify({"detail": f"Chat error: {str(e)}"}), 500

# ==========================================
# GOOGLE WORKSPACE INTEGRATIONS
# ==========================================

@app.route("/api/v1/workspace/gmail", methods=["GET"])
def google_gmail():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    x_google_token = request.headers.get("X-Google-Token")
    if not x_google_token: return jsonify({"sync_status": "unlinked", "emails": []})
    
    try:
        # Fetch recent emails
        resp = httpx.get(
            "https://www.googleapis.com/gmail/v1/users/me/messages?maxResults=10",
            headers={"Authorization": f"Bearer {x_google_token}"},
            timeout=10
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        
        emails = []
        for msg in messages[:5]:  # Limit to 5 for performance
            msg_detail = httpx.get(
                f"https://www.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                headers={"Authorization": f"Bearer {x_google_token}"},
                timeout=10
            )
            msg_detail.raise_for_status()
            msg_data = msg_detail.json()
            headers = msg_data.get("payload", {}).get("headers", [])
            email_obj = {
                "id": msg["id"],
                "from": next((h["value"] for h in headers if h["name"] == "From"), "Unknown"),
                "subject": next((h["value"] for h in headers if h["name"] == "Subject"), "(No Subject)"),
                "snippet": msg_data.get("snippet", "")
            }
            emails.append(email_obj)
        
        return jsonify({"sync_status": "active", "emails": emails})
    except httpx.HTTPStatusError as e:
        return jsonify({"sync_status": "error", "detail": f"Gmail API error: {e.response.text}", "emails": []}), e.response.status_code
    except Exception as e:
        return jsonify({"sync_status": "error", "detail": f"Error: {str(e)}", "emails": []}), 500

@app.route("/api/v1/workspace/tasks", methods=["GET"])
def google_tasks():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    x_google_token = request.headers.get("X-Google-Token")
    if not x_google_token: return jsonify({"sync_status": "unlinked", "tasks": []})
    
    try:
        # Fetch task lists
        lists_resp = httpx.get(
            "https://www.googleapis.com/tasks/v1/users/@me/lists",
            headers={"Authorization": f"Bearer {x_google_token}"},
            timeout=10
        )
        lists_resp.raise_for_status()
        task_lists = lists_resp.json().get("items", [])
        
        tasks = []
        for task_list in task_lists[:3]:  # Limit to 3 lists
            tasks_resp = httpx.get(
                f"https://www.googleapis.com/tasks/v1/lists/{task_list['id']}/tasks",
                headers={"Authorization": f"Bearer {x_google_token}"},
                timeout=10
            )
            tasks_resp.raise_for_status()
            for task in tasks_resp.json().get("items", [])[:5]:  # Limit to 5 tasks per list
                tasks.append({
                    "id": task["id"],
                    "list_id": task_list["id"],
                    "title": task.get("title", "Untitled"),
                    "status": task.get("status", "needsAction"),
                    "due": task.get("due", "")
                })
        
        return jsonify({"sync_status": "active", "tasks": tasks})
    except httpx.HTTPStatusError as e:
        return jsonify({"sync_status": "error", "detail": f"Tasks API error: {e.response.text}", "tasks": []}), e.response.status_code
    except Exception as e:
        return jsonify({"sync_status": "error", "detail": f"Error: {str(e)}", "tasks": []}), 500

# ==========================================
# DEVELOPER API & API KEY MANAGEMENT
# ==========================================

@app.route("/api/v1/developer/keys", methods=["GET", "POST"])
def api_keys():
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    if request.method == "GET":
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/rest/v1/api_keys",
                headers=get_supabase_headers(request.headers.get("Authorization")),
                params={"user_id": f"eq.{user_id}"}
            )
            resp.raise_for_status()
            return jsonify({"keys": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
    
    elif request.method == "POST":
        data = request.get_json()
        api_key = f"vex_{''.join(uuid.uuid4().hex.split('-')[:2])}_{uuid.uuid4().hex[:16]}"
        new_key = {
            "id": f"key_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "name": data.get("name", "Untitled Key"),
            "key": api_key,
            "created_at": _now(),
            "last_used_at": None,
            "is_active": True
        }
        try:
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/api_keys",
                headers=get_supabase_headers(request.headers.get("Authorization")),
                json=new_key
            )
            resp.raise_for_status()
            return jsonify({"key": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/v1/developer/keys/<key_id>", methods=["DELETE"])
def delete_api_key(key_id):
    user_id = get_current_user()
    if not user_id: return jsonify({"detail": "Unauthorized"}), 401

    try:
        resp = httpx.delete(
            f"{SUPABASE_URL}/rest/v1/api_keys?id=eq.{key_id}&user_id=eq.{user_id}",
            headers=get_supabase_headers(request.headers.get("Authorization"))
        )
        resp.raise_for_status()
        return jsonify({"status": "deleted"})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

# ==========================================
# PUBLIC API ENDPOINTS (API Key Authentication)
# ==========================================

def verify_api_key(api_key):
    """Verify API key and return user_id if valid"""
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/api_keys",
            headers=get_supabase_headers(),
            params={"key": f"eq.{api_key}", "is_active": "eq.true"}
        )
        resp.raise_for_status()
        keys = resp.json()
        if keys:
            # Update last_used_at
            httpx.patch(
                f"{SUPABASE_URL}/rest/v1/api_keys?id=eq.{keys[0]['id']}",
                headers=get_supabase_headers(),
                json={"last_used_at": _now()}
            )
            return keys[0]["user_id"]
        return None
    except:
        return None

@app.route("/api/public/v1/projects", methods=["GET"])
def public_projects():
    api_key = request.headers.get("X-API-Key")
    if not api_key: return jsonify({"detail": "Missing X-API-Key header"}), 401
    
    user_id = verify_api_key(api_key)
    if not user_id: return jsonify({"detail": "Invalid API key"}), 401
    
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/projects",
            headers=get_supabase_headers(),
            params={"user_id": f"eq.{user_id}"}
        )
        resp.raise_for_status()
        return jsonify({"projects": resp.json()})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/public/v1/projects/<project_id>/files", methods=["GET"])
def public_files(project_id):
    api_key = request.headers.get("X-API-Key")
    if not api_key: return jsonify({"detail": "Missing X-API-Key header"}), 401
    
    user_id = verify_api_key(api_key)
    if not user_id: return jsonify({"detail": "Invalid API key"}), 401
    
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/files",
            headers=get_supabase_headers(),
            params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"}
        )
        resp.raise_for_status()
        return jsonify({"files": resp.json()})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

@app.route("/api/public/v1/projects", methods=["POST"])
def public_create_project():
    api_key = request.headers.get("X-API-Key")
    if not api_key: return jsonify({"detail": "Missing X-API-Key header"}), 401
    
    user_id = verify_api_key(api_key)
    if not user_id: return jsonify({"detail": "Invalid API key"}), 401
    
    data = request.get_json()
    new_proj = {
        "id": f"prj_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "title": data.get("title", "Untitled Project"),
        "description": data.get("description", ""),
        "created_at": _now()
    }
    try:
        resp = httpx.post(
            f"{SUPABASE_URL}/rest/v1/projects",
            headers=get_supabase_headers(),
            json=new_proj
        )
        resp.raise_for_status()
        return jsonify({"project": resp.json()[0]}), 201
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code

# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"detail": "Not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"detail": "Internal server error"}), 500

# ==========================================
# MAIN ENTRY POINT
# ==========================================

# Export for Vercel
app = app

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
