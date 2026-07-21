from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from dotenv import load_dotenv
import os
import time
import uuid
from datetime import datetime, timezone
import httpx
import secrets

# -------- Setup --------
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-key-change-in-prod")
START_TIME = time.time()

# ==========================================
# SUPABASE HELPERS
# ==========================================

def get_supabase_headers(jwt_token=None, use_service_role=False):
    """Build proper headers for Supabase API calls."""
    api_key = SUPABASE_SERVICE_ROLE_KEY if use_service_role else SUPABASE_ANON_KEY
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation"  # <--- ADD THIS EXACT LINE
    }
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    return headers

# ==========================================
# AUTHENTICATION & AUTHORIZATION
# ==========================================

def extract_jwt_from_request():
    """Extract JWT from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]

def extract_api_key_from_request():
    """Extract API key from X-API-Key header."""
    return request.headers.get("X-API-Key", "")

def get_current_user_from_jwt():
    """Validate JWT securely by querying Supabase Auth. No local JWT secret needed."""
    token = extract_jwt_from_request()
    if not token:
        return None
    
    try:
        # Ask Supabase directly if this token is valid
        resp = httpx.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY
            },
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json().get("id")
    except Exception as e:
        print(f"Auth validation error: {e}")
        
    return None

def get_user_from_api_key():
    """Validate API key and extract user_id from database."""
    api_key = extract_api_key_from_request()
    if not api_key:
        return None
    
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/api_keys",
            headers=get_supabase_headers(use_service_role=True),
            params={"key": f"eq.{api_key}", "is_active": "eq.true"},
            timeout=5
        )
        resp.raise_for_status()
        keys = resp.json()
        if keys and len(keys) > 0:
            key_id = keys[0]["id"]
            httpx.patch(
                f"{SUPABASE_URL}/rest/v1/api_keys?id=eq.{key_id}",
                headers=get_supabase_headers(use_service_role=True),
                json={"last_used_at": datetime.now(timezone.utc).isoformat()},
                timeout=5
            )
            return keys[0]["user_id"]
    except Exception as e:
        print(f"API key validation error: {e}")
    
    return None

def get_current_user():
    """Get user from JWT or API key."""
    user_id = get_current_user_from_jwt()
    if user_id:
        return user_id
    return get_user_from_api_key()

def require_auth(f):
    """Decorator to require authentication."""
    def wrapper(*args, **kwargs):
        if not get_current_user():
            return jsonify({"detail": "Unauthorized. Token invalid or expired."}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

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
# HEALTH & STATUS
# ==========================================

@app.route("/api/health")
def health():
    return jsonify({"status": "online", "uptime_seconds": int(time.time() - START_TIME)})

# ==========================================
# PROJECTS CRUD API
# ==========================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@app.route("/api/v1/projects", methods=["GET", "POST"])
@require_auth
def projects_api():
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    if request.method == "GET":
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/rest/v1/projects",
                headers=get_supabase_headers(jwt_token),
                params={"user_id": f"eq.{user_id}"},
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"projects": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

    elif request.method == "POST":
        data = request.get_json() or {}
        title = data.get("title", "").strip() or "Untitled Project"
        description = data.get("description", "").strip()
        new_proj = {
            "id": f"prj_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": title,
            "description": description,
            "created_at": _now()
        }
        try:
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/projects",
                headers=get_supabase_headers(jwt_token),
                json=new_proj,
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"project": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route("/api/v1/projects/<project_id>", methods=["DELETE"])
@require_auth
def delete_project_api(project_id):
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    try:
        resp = httpx.delete(
            f"{SUPABASE_URL}/rest/v1/projects",
            headers=get_supabase_headers(jwt_token),
            params={"id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
            timeout=10
        )
        resp.raise_for_status()
        
        httpx.delete(
            f"{SUPABASE_URL}/rest/v1/files",
            headers=get_supabase_headers(jwt_token),
            params={"project_id": f"eq.{project_id}"},
            timeout=10
        )
        
        return jsonify({"status": "deleted"})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
    except Exception as e:
        return jsonify({"detail": f"Error: {str(e)}"}), 500

# ==========================================
# FILES CRUD API
# ==========================================

@app.route("/api/v1/projects/<project_id>/files", methods=["GET", "POST"])
@require_auth
def files_api(project_id):
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    if request.method == "GET":
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/rest/v1/files",
                headers=get_supabase_headers(jwt_token),
                params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"files": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

    elif request.method == "POST":
        data = request.get_json() or {}
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
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/files",
                headers=get_supabase_headers(jwt_token),
                json=new_file,
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"file": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route("/api/v1/projects/<project_id>/files/<file_id>", methods=["PUT", "DELETE"])
@require_auth
def file_detail_api(project_id, file_id):
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    if request.method == "PUT":
        data = request.get_json() or {}
        patch_data = {"updated_at": _now()}
        if "title" in data:
            patch_data["title"] = data["title"]
        if "content" in data:
            patch_data["content"] = data["content"]
        if "folder" in data:
            patch_data["folder"] = data["folder"]
        if "extension" in data:
            patch_data["extension"] = data["extension"]
        
        try:
            resp = httpx.patch(
                f"{SUPABASE_URL}/rest/v1/files",
                headers=get_supabase_headers(jwt_token),
                params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
                json=patch_data,
                timeout=10
            )
            resp.raise_for_status()
            result = resp.json()
            if result:
                return jsonify({"file": result[0]})
            return jsonify({"detail": "File not found"}), 404
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

    elif request.method == "DELETE":
        try:
            resp = httpx.delete(
                f"{SUPABASE_URL}/rest/v1/files",
                headers=get_supabase_headers(jwt_token),
                params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"status": "deleted"})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

# ==========================================
# DEVELOPER API - API KEY MANAGEMENT
# ==========================================

@app.route("/api/v1/developer/keys", methods=["GET", "POST"])
@require_auth
def developer_keys():
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    if request.method == "GET":
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/rest/v1/api_keys",
                headers=get_supabase_headers(jwt_token),
                params={"user_id": f"eq.{user_id}"},
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"keys": resp.json()})
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

    elif request.method == "POST":
        data = request.get_json() or {}
        name = data.get("name", "Untitled Key").strip()
        
        api_key = f"vex_{secrets.token_urlsafe(32)}"
        
        new_key = {
            "id": f"key_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "name": name,
            "key": api_key,
            "created_at": _now(),
            "is_active": True
        }
        
        try:
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/api_keys",
                headers=get_supabase_headers(jwt_token),
                json=new_key,
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"key": resp.json()[0]}), 201
        except httpx.HTTPStatusError as e:
            return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route("/api/v1/developer/keys/<key_id>", methods=["DELETE"])
@require_auth
def delete_developer_key(key_id):
    user_id = get_current_user()
    jwt_token = extract_jwt_from_request()
    
    try:
        resp = httpx.delete(
            f"{SUPABASE_URL}/rest/v1/api_keys",
            headers=get_supabase_headers(jwt_token),
            params={"id": f"eq.{key_id}", "user_id": f"eq.{user_id}"},
            timeout=10
        )
        resp.raise_for_status()
        return jsonify({"status": "deleted"})
    except httpx.HTTPStatusError as e:
        return jsonify({"detail": f"Supabase error: {e.response.text}"}), e.response.status_code
    except Exception as e:
        return jsonify({"detail": f"Error: {str(e)}"}), 500

# ==========================================
# PUBLIC API ENDPOINTS (API Key Protected)
# ==========================================

@app.route("/api/public/v1/projects", methods=["GET", "POST"])
def public_projects():
    user_id = get_user_from_api_key()
    if not user_id:
        return jsonify({"detail": "Invalid or missing API key"}), 401
    
    if request.method == "GET":
        try:
            resp = httpx.get(
                f"{SUPABASE_URL}/rest/v1/projects",
                headers=get_supabase_headers(use_service_role=True),
                params={"user_id": f"eq.{user_id}"},
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"projects": resp.json()})
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

    elif request.method == "POST":
        data = request.get_json() or {}
        title = data.get("title", "").strip() or "Untitled Project"
        description = data.get("description", "").strip()
        new_proj = {
            "id": f"prj_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": title,
            "description": description,
            "created_at": _now()
        }
        try:
            resp = httpx.post(
                f"{SUPABASE_URL}/rest/v1/projects",
                headers=get_supabase_headers(use_service_role=True),
                json=new_proj,
                timeout=10
            )
            resp.raise_for_status()
            return jsonify({"project": resp.json()[0]}), 201
        except Exception as e:
            return jsonify({"detail": f"Error: {str(e)}"}), 500

@app.route("/api/public/v1/projects/<project_id>/files", methods=["GET"])
def public_project_files(project_id):
    user_id = get_user_from_api_key()
    if not user_id:
        return jsonify({"detail": "Invalid or missing API key"}), 401
    
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/files",
            headers=get_supabase_headers(use_service_role=True),
            params={"project_id": f"eq.{project_id}", "user_id": f"eq.{user_id}"},
            timeout=10
        )
        resp.raise_for_status()
        return jsonify({"files": resp.json()})
    except Exception as e:
        return jsonify({"detail": f"Error: {str(e)}"}), 500

# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"detail": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"detail": "Internal server error"}), 500

# ==========================================
# MAIN ENTRY POINT
# ==========================================

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)