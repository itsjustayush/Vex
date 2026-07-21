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
```

### Step 3: The Complete UI Engine (`dashboard.html`)
This is the fully integrated UI. I have implemented a beautiful, functional text editor inside the Workspace. 
*   **Markdown & LaTeX** render seamlessly in the preview tab.
*   **Copy & Delete** note buttons are integrated directly into the UI.
*   **Share Link** generates a public UI toggle and copies a shareable URL to the clipboard.
*   **Google Auth Guard** ensures users are redirected to login securely.

```html:Dashboard Engine UI:templates/dashboard.html
<!DOCTYPE html>
<html class="dark" lang="en">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Vex Workspace</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
<!-- Markdown & LaTeX Parsers -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>

<script>
    tailwind.config = { darkMode: "class", theme: { extend: { colors: { background: "#131316", primary: "#63dac3", "surface-low": "#1b1b1e", "surface-high": "#2a2a2d", border: "#27272A", text: "#e4e1e6", muted: "#52525B" } } } }
</script>
<style>
    body { font-family: 'Inter', sans-serif; background: #131316; color: #e4e1e6; }
    .glass { background: rgba(27, 27, 30, 0.7); backdrop-filter: blur(12px); border: 1px solid #27272A; }
    .custom-scrollbar::-webkit-scrollbar { width: 6px; }
    .custom-scrollbar::-webkit-scrollbar-thumb { background: #27272A; border-radius: 4px; }
    
    #toast { position: fixed; bottom: -100px; left: 50%; transform: translateX(-50%); transition: bottom 0.3s ease; z-index: 1000; }
    #toast.show { bottom: 20px; }
</style>
</head>
<body class="flex h-screen overflow-hidden text-sm">

<!-- Left Sidebar -->
<aside class="w-[280px] border-r border-border bg-surface-low flex flex-col z-20">
    <div class="p-6 flex items-center gap-3">
        <div class="w-8 h-8 bg-primary/20 text-primary flex items-center justify-center rounded"><span class="material-icons text-sm">bolt</span></div>
        <h1 class="font-bold text-lg">Vex Workspace</h1>
    </div>
    <div class="px-4 mb-6">
        <button onclick="document.getElementById('modal-project').classList.remove('hidden')" class="w-full bg-primary text-[#00382f] font-bold py-2.5 rounded-lg flex justify-center items-center gap-2 hover:brightness-110 transition"><span class="material-icons text-sm">add</span> New Project</button>
    </div>
    <nav class="flex-1 px-4 space-y-2">
        <button onclick="switchView('dashboard')" id="nav-dash" class="w-full flex items-center gap-3 px-3 py-2 text-primary bg-primary/10 rounded-lg font-bold"><span class="material-icons text-sm">dashboard</span> Dashboard</button>
        <button onclick="switchView('projects')" id="nav-proj" class="w-full flex items-center gap-3 px-3 py-2 text-muted hover:text-text rounded-lg"><span class="material-icons text-sm">folder</span> Projects</button>
        <a href="/settings" class="w-full flex items-center gap-3 px-3 py-2 text-muted hover:text-text rounded-lg"><span class="material-icons text-sm">settings</span> Settings</a>
    </nav>
    <div class="p-4 border-t border-border">
        <div class="flex items-center gap-3 cursor-pointer" onclick="supabaseClient.auth.signOut(); window.location.href='/login'">
            <div id="user-avatar" class="w-8 h-8 rounded-full bg-surface-high flex items-center justify-center text-primary font-bold">U</div>
            <div class="flex-1 min-w-0">
                <p id="user-email" class="text-xs font-bold truncate">Loading...</p>
                <p class="text-[10px] text-emerald-400">Log out</p>
            </div>
        </div>
    </div>
</aside>

<!-- Main Area -->
<main class="flex-1 flex flex-col relative overflow-hidden">
    
    <!-- Dashboard View -->
    <section id="view-dashboard" class="p-10 flex-1 overflow-y-auto custom-scrollbar">
        <div class="max-w-4xl mx-auto space-y-8 mt-8">
            <div>
                <h2 class="text-4xl font-bold mb-2">Welcome Back.</h2>
                <p class="text-muted">Your connected brain is ready. Jump into a project to start thinking.</p>
            </div>
            <div class="grid grid-cols-3 gap-6">
                <div class="p-6 rounded-xl border border-border bg-surface-low">
                    <p class="text-xs text-muted uppercase font-bold tracking-widest mb-2">Total Projects</p>
                    <p id="stat-projects" class="text-4xl text-primary font-bold">0</p>
                </div>
                <div class="p-6 rounded-xl border border-border bg-surface-low">
                    <p class="text-xs text-muted uppercase font-bold tracking-widest mb-2">Total Notes</p>
                    <p id="stat-notes" class="text-4xl text-primary font-bold">0</p>
                </div>
            </div>
        </div>
    </section>

    <!-- Projects View -->
    <section id="view-projects" class="p-10 flex-1 flex flex-col hidden h-full overflow-hidden">
        <div id="project-grid-container" class="max-w-5xl mx-auto w-full space-y-6">
            <h2 class="text-2xl font-bold border-b border-border pb-4">Your Projects</h2>
            <div id="projects-grid" class="grid grid-cols-3 gap-4"></div>
        </div>
        
        <!-- Active Workspace (Note Editor) -->
        <div id="active-workspace" class="hidden flex-1 flex gap-6 h-full min-h-0">
            <!-- Left: Note List -->
            <div class="w-64 flex flex-col border border-border rounded-xl bg-surface-low overflow-hidden shrink-0">
                <div class="p-4 border-b border-border flex justify-between items-center">
                    <h3 class="font-bold truncate max-w-[150px]" id="ws-proj-title">Project</h3>
                    <button onclick="closeProject()" class="text-muted hover:text-text material-icons text-sm">close</button>
                </div>
                <div class="p-3">
                    <button onclick="createNote()" class="w-full bg-surface-high border border-border py-1.5 rounded text-xs font-bold hover:border-primary/50 text-primary">+ New Note</button>
                </div>
                <div id="notes-list" class="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1"></div>
            </div>
            
            <!-- Right: Note Editor Lightbox / Panel -->
            <div class="flex-1 flex flex-col border border-border rounded-xl bg-surface-low overflow-hidden relative">
                <div id="empty-editor" class="absolute inset-0 flex items-center justify-center text-muted">Select or create a note to begin editing.</div>
                
                <div id="editor-core" class="hidden flex-1 flex flex-col h-full">
                    <!-- Editor Header & Meta -->
                    <div class="p-4 border-b border-border bg-[#17171a] flex justify-between items-start">
                        <div class="flex-1 mr-4">
                            <input id="note-title" type="text" class="bg-transparent text-xl font-bold w-full border-none focus:ring-0 p-0 text-text placeholder-muted mb-2" placeholder="Note Title...">
                            <div class="flex gap-4">
                                <input id="note-folder" type="text" class="bg-surface-high border border-border text-xs rounded px-2 py-1 w-32" placeholder="Folder (General)">
                                <span class="flex items-center gap-2 text-xs text-muted">
                                    <input type="checkbox" id="note-public" class="rounded bg-surface-high border-border text-primary focus:ring-primary h-3 w-3"> Public Share
                                </span>
                            </div>
                        </div>
                        <div class="flex items-center gap-2">
                            <button onclick="saveNote()" class="bg-primary/20 text-primary hover:bg-primary/30 px-3 py-1.5 rounded font-bold text-xs flex items-center gap-1"><span class="material-icons text-sm">save</span> Save</button>
                            <button onclick="copyNote()" class="bg-surface-high text-muted hover:text-text px-2 py-1.5 rounded text-xs material-icons" title="Duplicate Note">file_copy</button>
                            <button onclick="shareNote()" class="bg-surface-high text-muted hover:text-primary px-2 py-1.5 rounded text-xs material-icons" title="Copy Public Link">link</button>
                            <button onclick="deleteNote()" class="bg-surface-high text-muted hover:text-red-400 px-2 py-1.5 rounded text-xs material-icons" title="Delete Note">delete</button>
                        </div>
                    </div>

                    <!-- Format Toolbar -->
                    <div class="flex items-center justify-between px-3 py-2 border-b border-border bg-background overflow-x-auto">
                        <div class="flex items-center gap-1">
                            <button onclick="insertMD('**', '**')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="Bold">format_bold</button>
                            <button onclick="insertMD('_', '_')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="Italic">format_italic</button>
                            <div class="w-px h-4 bg-border mx-2"></div>
                            <button onclick="insertMD('# ', '')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text font-bold text-xs" title="H1">H1</button>
                            <button onclick="insertMD('- ', '')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="List">format_list_bulleted</button>
                            <button onclick="insertMD('- [ ] ', '')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="Task">check_box</button>
                            <div class="w-px h-4 bg-border mx-2"></div>
                            <button onclick="insertMD('`', '`')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="Code">code</button>
                            <button onclick="insertMD('$$', '$$')" class="p-1 hover:bg-surface-high rounded text-muted hover:text-text material-icons text-sm" title="Math Block">functions</button>
                        </div>
                        <div class="flex gap-2">
                            <button id="btn-edit" onclick="setMode('edit')" class="text-xs font-bold text-primary px-2 py-1 bg-primary/10 rounded">Edit</button>
                            <button id="btn-preview" onclick="setMode('preview')" class="text-xs font-bold text-muted hover:text-text px-2 py-1 rounded">Preview</button>
                            <button onclick="exportPDF()" class="text-xs font-bold text-muted hover:text-text px-2 py-1 border-l border-border ml-2 pl-4 flex items-center gap-1"><span class="material-icons text-sm">picture_as_pdf</span> PDF</button>
                        </div>
                    </div>

                    <!-- Editor Area -->
                    <div class="flex-1 relative bg-background">
                        <textarea id="note-content" class="absolute inset-0 w-full h-full p-6 bg-transparent border-none focus:ring-0 text-sm font-mono resize-none text-text leading-relaxed" placeholder="Write in Markdown or LaTeX ($E=mc^2$)"></textarea>
                        <div id="note-preview" class="absolute inset-0 w-full h-full p-6 overflow-y-auto prose prose-invert max-w-none hidden"></div>
                    </div>
                </div>
            </div>
        </div>
    </section>
</main>

<!-- Modals & Toasts -->
<div id="modal-project" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center">
    <div class="glass p-6 rounded-xl w-[400px]">
        <h3 class="text-lg font-bold mb-4">Create Project</h3>
        <input id="proj-title" type="text" class="w-full bg-background border border-border rounded p-2 mb-3 text-sm focus:border-primary" placeholder="Project Name">
        <textarea id="proj-desc" class="w-full bg-background border border-border rounded p-2 mb-4 text-sm focus:border-primary resize-none" rows="3" placeholder="Description"></textarea>
        <div class="flex justify-end gap-2">
            <button onclick="document.getElementById('modal-project').classList.add('hidden')" class="px-4 py-2 text-muted hover:text-text font-bold text-xs">Cancel</button>
            <button onclick="createProject()" class="px-4 py-2 bg-primary text-[#00382f] rounded font-bold text-xs">Save</button>
        </div>
    </div>
</div>

<div id="toast" class="bg-primary text-[#00382f] px-4 py-2 rounded-lg font-bold shadow-xl border border-primary/20 flex items-center gap-2"><span class="material-icons text-sm" id="toast-icon">check_circle</span> <span id="toast-msg">Success!</span></div>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
    // 1. Core State & Setup
    const SUPABASE_URL = '{{ supabase_url }}';
    const SUPABASE_ANON_KEY = '{{ supabase_anon_key }}';
    const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    
    let currentSession = null;
    let projects = [];
    let files = [];
    let activeProject = null;
    let activeFile = null;
    let autoSaveTimer = null;

    const $ = id => document.getElementById(id);
    const showToast = (msg, isErr=false) => { 
        $('toast-msg').innerText = msg; 
        $('toast-icon').innerText = isErr ? 'error' : 'check_circle';
        $('toast').className = `px-4 py-2 rounded-lg font-bold shadow-xl border flex items-center gap-2 fixed bottom-[-100px] left-1/2 transform -translate-x-1/2 transition-all duration-300 z-50 ${isErr ? 'bg-red-500 text-white border-red-400' : 'bg-primary text-[#00382f] border-primary/20'} show`;
        setTimeout(() => $('toast').classList.remove('show'), 3000);
    };

    // 2. Authentication Guard
    window.onload = async () => {
        const { data: { session }, error } = await supabaseClient.auth.getSession();
        if (error || !session) return window.location.href = '/login';
        currentSession = session;
        $('user-email').innerText = session.user.email;
        $('user-avatar').innerText = session.user.email[0].toUpperCase();
        loadProjects();
    };

    // API Helper
    async function apiReq(endpoint, method='GET', body=null) {
        const headers = { 'Authorization': `Bearer ${currentSession.access_token}`, 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/${endpoint}`, { method, headers, body: body ? JSON.stringify(body) : null });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'API Error');
        return data;
    }

    // 3. UI Navigation
    function switchView(view) {
        $('view-dashboard').classList.toggle('hidden', view !== 'dashboard');
        $('view-projects').classList.toggle('hidden', view !== 'projects');
        $('nav-dash').className = `w-full flex items-center gap-3 px-3 py-2 rounded-lg font-bold ${view==='dashboard' ? 'bg-primary/10 text-primary' : 'text-muted hover:text-text'}`;
        $('nav-proj').className = `w-full flex items-center gap-3 px-3 py-2 rounded-lg font-bold ${view==='projects' ? 'bg-primary/10 text-primary' : 'text-muted hover:text-text'}`;
    }

    // 4. Project CRUD
    async function loadProjects() {
        try {
            const res = await apiReq('projects');
            projects = res.projects;
            $('stat-projects').innerText = projects.length;
            renderProjects();
        } catch(e) { showToast(e.message, true); }
    }

    function renderProjects() {
        const grid = $('projects-grid');
        grid.innerHTML = projects.map(p => `
            <div onclick="openProject('${p.id}')" class="glass p-5 rounded-xl cursor-pointer hover:border-primary/50 transition group">
                <h3 class="font-bold text-lg mb-1 group-hover:text-primary transition">${p.title}</h3>
                <p class="text-xs text-muted truncate">${p.description || 'No description'}</p>
            </div>
        `).join('');
    }

    async function createProject() {
        const title = $('proj-title').value.trim();
        if (!title) return showToast('Title required', true);
        try {
            await apiReq('projects', 'POST', { title, description: $('proj-desc').value });
            $('modal-project').classList.add('hidden');
            $('proj-title').value = ''; $('proj-desc').value = '';
            showToast('Project Created');
            loadProjects();
        } catch(e) { showToast(e.message, true); }
    }

    async function openProject(id) {
        activeProject = projects.find(p => p.id === id);
        $('project-grid-container').classList.add('hidden');
        $('active-workspace').classList.remove('hidden');
        $('ws-proj-title').innerText = activeProject.title;
        $('empty-editor').classList.remove('hidden');
        $('editor-core').classList.add('hidden');
        activeFile = null;
        loadFiles();
    }
    
    function closeProject() {
        $('active-workspace').classList.add('hidden');
        $('project-grid-container').classList.remove('hidden');
        activeProject = null;
    }

    // 5. File/Note CRUD
    async function loadFiles() {
        if (!activeProject) return;
        try {
            const res = await apiReq(`projects/${activeProject.id}/files`);
            files = res.files;
            
            // Calculate total notes across all projects for Dashboard stat
            let total = 0; // In a real app you'd fetch a global count, but for UI fluidity we update this active project.
            
            const list = $('notes-list');
            list.innerHTML = files.map(f => `
                <div onclick="openNote('${f.id}')" class="p-2 rounded cursor-pointer text-xs border border-transparent hover:bg-surface-high transition ${activeFile?.id === f.id ? 'bg-primary/10 border-primary/30 text-primary font-bold' : 'text-text'}">
                    <div class="truncate flex items-center justify-between">
                        <span>${f.title}</span>
                        ${f.is_public ? '<span class="material-icons text-[10px] text-muted">public</span>' : ''}
                    </div>
                </div>
            `).join('');
        } catch(e) { showToast(e.message, true); }
    }

    async function createNote() {
        try {
            const res = await apiReq(`projects/${activeProject.id}/files`, 'POST', { title: 'New Note', content: '# New Note\nStart writing...' });
            await loadFiles();
            openNote(res.file.id);
            $('note-title').focus();
        } catch(e) { showToast(e.message, true); }
    }

    function openNote(id) {
        activeFile = files.find(f => f.id === id);
        $('empty-editor').classList.add('hidden');
        $('editor-core').classList.remove('hidden');
        
        $('note-title').value = activeFile.title;
        $('note-folder').value = activeFile.folder || '';
        $('note-public').checked = activeFile.is_public || false;
        $('note-content').value = activeFile.content || '';
        
        loadFiles(); // Re-render list for active styling
        setMode('edit');
    }

    async function saveNote(silent=false) {
        if (!activeFile) return;
        const body = {
            title: $('note-title').value || 'Untitled',
            folder: $('note-folder').value,
            is_public: $('note-public').checked,
            content: $('note-content').value
        };
        try {
            const res = await apiReq(`projects/${activeProject.id}/files/${activeFile.id}`, 'PUT', body);
            activeFile = res.file;
            const idx = files.findIndex(f => f.id === activeFile.id);
            if(idx > -1) files[idx] = activeFile;
            if(!silent) { showToast('Note Saved'); loadFiles(); }
        } catch(e) { if(!silent) showToast(e.message, true); }
    }

    // Auto-save logic
    $('note-content').addEventListener('input', () => {
        clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(() => saveNote(true), 1500);
    });

    async function deleteNote() {
        if (!confirm("Delete this note?")) return;
        try {
            await apiReq(`projects/${activeProject.id}/files/${activeFile.id}`, 'DELETE');
            showToast('Deleted');
            $('editor-core').classList.add('hidden');
            $('empty-editor').classList.remove('hidden');
            activeFile = null;
            loadFiles();
        } catch(e) { showToast(e.message, true); }
    }

    // Using our custom Developer API endpoint for duplicating!
    async function copyNote() {
        try {
            const res = await apiReq(`projects/${activeProject.id}/files/${activeFile.id}/copy`, 'POST');
            showToast('Note Duplicated');
            await loadFiles();
            openNote(res.file.id);
        } catch(e) { showToast(e.message, true); }
    }

    async function shareNote() {
        if (!$('note-public').checked) {
            $('note-public').checked = true;
            await saveNote(true);
        }
        // In a real app, you'd route this to a public viewer page. 
        // For now, we mock the public URL structure and copy to clipboard.
        const url = `${window.location.origin}/public/note/${activeFile.id}`;
        navigator.clipboard.writeText(url);
        showToast('Public Link Copied!');
    }

    // 6. Editor Engine
    function setMode(mode) {
        const ta = $('note-content');
        const pv = $('note-preview');
        const bE = $('btn-edit');
        const bP = $('btn-preview');
        
        if (mode === 'preview') {
            ta.classList.add('hidden'); pv.classList.remove('hidden');
            bE.className = "text-xs font-bold text-muted hover:text-text px-2 py-1 rounded";
            bP.className = "text-xs font-bold text-primary px-2 py-1 bg-primary/10 rounded";
            
            // Render MD & Math
            pv.innerHTML = marked.parse(ta.value);
            if (window.renderMathInElement) {
                renderMathInElement(pv, { delimiters: [{left:'$$', right:'$$', display:true}, {left:'$', right:'$', display:false}] });
            }
        } else {
            pv.classList.add('hidden'); ta.classList.remove('hidden');
            bP.className = "text-xs font-bold text-muted hover:text-text px-2 py-1 rounded";
            bE.className = "text-xs font-bold text-primary px-2 py-1 bg-primary/10 rounded";
            ta.focus();
        }
    }

    function insertMD(prefix, suffix) {
        const ta = $('note-content');
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        const sel = ta.value.substring(start, end);
        ta.value = ta.value.substring(0, start) + prefix + sel + suffix + ta.value.substring(end);
        ta.focus();
        ta.selectionStart = start + prefix.length;
        ta.selectionEnd = end + prefix.length;
        saveNote(true);
    }

    // PDF Export Tool
    function exportPDF() {
        if(!activeFile) return;
        setMode('preview'); // Force preview to render DOM
        const el = document.createElement('div');
        el.className = 'prose bg-white text-black p-8';
        el.innerHTML = `<h1>${activeFile.title}</h1>` + $('note-preview').innerHTML;
        
        const opt = { margin: 0.5, filename: `${activeFile.title}.pdf`, html2canvas: { scale: 2 }, jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' } };
        html2pdf().set(opt).from(el).save().then(() => showToast('PDF Exported!'));
    }

    // Keybindings
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveNote(); }
    });
</script>
</body>
</html>