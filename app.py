import os
import time
import uuid
import httpx
import secrets
import jwt
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

app = Flask(__name__)
application = app # Tells Vercel explicitly where the WSGI handler is
START_TIME = time.time()

# ==========================================
# SUPABASE & AUTH HELPERS
# ==========================================

def get_supabase_headers(jwt_token=None, use_service_role=False):
    api_key = SUPABASE_SERVICE_ROLE_KEY if use_service_role else SUPABASE_ANON_KEY
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation"  # CRITICAL: Forces Supabase to return inserted data
    }
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    return headers

def extract_jwt_from_request():
    auth_header = request.headers.get("Authorization", "")
    return auth_header[7:] if auth_header.startswith("Bearer ") else None

def extract_api_key_from_request():
    return request.headers.get("X-API-Key", "")

def get_current_user_from_jwt():
    token = extract_jwt_from_request()
    if not token: return None
    try:
        resp = httpx.get(f"{SUPABASE_URL}/auth/v1/user", headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY}, timeout=5)
        if resp.status_code == 200: return resp.json().get("id")
    except Exception: pass
    return None

def get_user_from_api_key():
    api_key = extract_api_key_from_request()
    if not api_key: return None
    try:
        resp = httpx.get(f"{SUPABASE_URL}/rest/v1/api_keys", headers=get_supabase_headers(use_service_role=True), params={"key": f"eq.{api_key}", "is_active": "eq.true"}, timeout=5)
        keys = resp.json()
        if keys:
            httpx.patch(f"{SUPABASE_URL}/rest/v1/api_keys?id=eq.{keys[0]['id']}", headers=get_supabase_headers(use_service_role=True), json={"last_used_at": datetime.now(timezone.utc).isoformat()})
            return keys[0]["user_id"]
    except Exception: pass
    return None

def get_current_user():
    return get_current_user_from_jwt() or get_user_from_api_key()

def require_auth(f):
    def wrapper(*args, **kwargs):
        if not get_current_user(): return jsonify({"detail": "Unauthorized. Token invalid or expired."}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def _now(): return datetime.now(timezone.utc).isoformat()

# ==========================================
# FRONTEND TEMPLATE ROUTES
# ==========================================

@app.route("/")
def index_page(): return render_template("index.html")

@app.route("/login")
def login_page(): return render_template("login.html")

@app.route("/dashboard")
def dashboard_page(): return render_template("dashboard.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/settings")
def settings_page(): return render_template("settings.html", supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)

@app.route("/docs")
def docs_page(): return render_template("docs.html")

@app.route("/status")
def status_page(): return render_template("status.html")

@app.route("/auth/callback")
def callback_page(): return render_template("callback.html")

@app.route("/api/health")
def health(): return jsonify({"status": "online", "uptime_seconds": int(time.time() - START_TIME)})

# ==========================================
# CORE API: PROJECTS
# ==========================================

@app.route("/api/v1/projects", methods=["GET", "POST"])
@require_auth
def projects_api():
    user_id = get_current_user()
    token = extract_jwt_from_request()
    
    if request.method == "GET":
        resp = httpx.get(f"{SUPABASE_URL}/rest/v1/projects", headers=get_supabase_headers(token), params={"user_id": f"eq.{user_id}", "order": "created_at.desc"})
        return jsonify({"projects": resp.json()}), resp.status_code

    data = request.get_json() or {}
    new_proj = {"id": f"prj_{uuid.uuid4().hex[:12]}", "user_id": user_id, "title": data.get("title", "Untitled").strip() or "Untitled", "description": data.get("description", "").strip(), "created_at": _now()}
    resp = httpx.post(f"{SUPABASE_URL}/rest/v1/projects", headers=get_supabase_headers(token), json=new_proj)
    return jsonify({"project": resp.json()[0] if resp.json() else new_proj}), 201

@app.route("/api/v1/projects/<project_id>", methods=["DELETE"])
@require_auth
def delete_project_api(project_id):
    user_id = get_current_user()
    token = extract_jwt_from_request()
    resp = httpx.delete(f"{SUPABASE_URL}/rest/v1/projects", headers=get_supabase_headers(token), params={"id": f"eq.{project_id}", "user_id": f"eq.{user_id}"})
    # Clean up associated files
    httpx.delete(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), params={"project_id": f"eq.{project_id}"})
    return jsonify({"status": "deleted"}), resp.status_code

# ==========================================
# CORE API: FILES / NOTES
# ==========================================

@app.route("/api/v1/projects/<project_id>/files", methods=["GET", "POST"])
@require_auth
def files_api(project_id):
    user_id = get_current_user()
    token = extract_jwt_from_request()
    
    if request.method == "GET":
        resp = httpx.get(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}", "order": "updated_at.desc"})
        return jsonify({"files": resp.json()}), resp.status_code

    data = request.get_json() or {}
    new_file = {
        "id": f"nt_{uuid.uuid4().hex[:12]}", "user_id": user_id, "project_id": project_id,
        "title": data.get("title", "Untitled Note"), "content": data.get("content", ""),
        "folder": data.get("folder", "General"), "extension": data.get("extension", "md"),
        "is_public": False, "created_at": _now(), "updated_at": _now()
    }
    resp = httpx.post(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), json=new_file)
    return jsonify({"file": resp.json()[0] if resp.json() else new_file}), 201

@app.route("/api/v1/projects/<project_id>/files/<file_id>", methods=["PUT", "DELETE"])
@require_auth
def file_detail_api(project_id, file_id):
    user_id = get_current_user()
    token = extract_jwt_from_request()
    
    if request.method == "PUT":
        data = request.get_json() or {}
        patch_data = {"updated_at": _now()}
        for key in ["title", "content", "folder", "extension", "is_public"]:
            if key in data: patch_data[key] = data[key]
            
        resp = httpx.patch(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"}, json=patch_data)
        if resp.json(): return jsonify({"file": resp.json()[0]})
        return jsonify({"detail": "File not found"}), 404

    elif request.method == "DELETE":
        resp = httpx.delete(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"})
        return jsonify({"status": "deleted"}), resp.status_code

@app.route("/api/v1/projects/<project_id>/files/<file_id>/copy", methods=["POST"])
@require_auth
def copy_file_api(project_id, file_id):
    """Developer API: Duplicate a note."""
    user_id = get_current_user()
    token = extract_jwt_from_request()
    
    # 1. Fetch original
    resp = httpx.get(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"})
    if not resp.json(): return jsonify({"detail": "Source file not found"}), 404
    original = resp.json()[0]
    
    # 2. Create copy
    new_file = {
        "id": f"nt_{uuid.uuid4().hex[:12]}", "user_id": user_id, "project_id": project_id,
        "title": f"Copy of {original.get('title', 'Note')}", "content": original.get("content", ""),
        "folder": original.get("folder", "General"), "extension": original.get("extension", "md"),
        "is_public": False, "created_at": _now(), "updated_at": _now()
    }
    httpx.post(f"{SUPABASE_URL}/rest/v1/files", headers=get_supabase_headers(token), json=new_file)
    return jsonify({"file": new_file}), 201

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
