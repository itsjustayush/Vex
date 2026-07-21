"""
Vex Workspace — FastAPI Backend
Handles Supabase Database CRUD, Google Calendar Proxy, and serves HTML templates.
"""

import os
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# -------- Setup --------
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
START_TIME = time.time()

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vex Workspace API")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# FRONTEND TEMPLATE ROUTES
# ==========================================

def render_page(request: Request, template_name: str):
    return templates.TemplateResponse(template_name, {
        "request": request,
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY
    })

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request): return render_page(request, "index.html")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request): return render_page(request, "login.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request): return render_page(request, "dashboard.html")

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request): return render_page(request, "settings.html")

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request): return render_page(request, "docs.html")

@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request): return render_page(request, "status.html")

@app.get("/auth/callback", response_class=HTMLResponse)
async def callback_page(request: Request): return render_page(request, "callback.html")

# ==========================================
# AUTHENTICATION GUARD
# ==========================================

def get_current_user(authorization: Annotated[Optional[str], Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        if SUPABASE_JWT_SECRET:
            payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        else:
            payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id: raise HTTPException(status_code=401, detail="Invalid token (no sub)")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token invalid: {e}")

# ==========================================
# SUPABASE REST API CRUD ROUTES
# ==========================================

def _now() -> str: return datetime.now(timezone.utc).isoformat()
def supa_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

class ProjectIn(BaseModel): title: str; description: Optional[str] = ""
class FileIn(BaseModel): title: str = "Untitled Note"; content: str = ""; folder: str = "General"; extension: str = "md"
class FilePatch(BaseModel): title: Optional[str] = None; content: Optional[str] = None; folder: Optional[str] = None; extension: Optional[str] = None

@app.get("/api/health")
async def health():
    return {"status": "online", "uptime_seconds": int(time.time() - START_TIME)}

@app.get("/api/v1/projects")
async def list_projects(user_id: str = Depends(get_current_user)):
    url = f"{SUPABASE_URL}/rest/v1/projects?user_id=eq.{user_id}&order=created_at.desc"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=supa_headers())
        return {"projects": r.json() if r.status_code == 200 else []}

@app.post("/api/v1/projects")
async def create_project(payload: ProjectIn, user_id: str = Depends(get_current_user)):
    doc = {"id": f"prj_{uuid.uuid4().hex[:12]}", "user_id": user_id, "title": payload.title.strip() or "Untitled Project", "description": payload.description.strip(), "created_at": _now()}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SUPABASE_URL}/rest/v1/projects", json=doc, headers=supa_headers())
        if r.status_code >= 400: raise HTTPException(status_code=500, detail="Failed to create project")
        return {"project": r.json()[0]}

@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user)):
    async with httpx.AsyncClient() as client:
        await client.delete(f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&user_id=eq.{user_id}", headers=supa_headers())
        return {"status": "deleted"}

@app.get("/api/v1/projects/{project_id}/files")
async def list_files(project_id: str, user_id: str = Depends(get_current_user)):
    url = f"{SUPABASE_URL}/rest/v1/files?project_id=eq.{project_id}&user_id=eq.{user_id}&order=updated_at.desc"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=supa_headers())
        return {"files": r.json() if r.status_code == 200 else []}

@app.post("/api/v1/projects/{project_id}/files")
async def create_file(project_id: str, payload: FileIn, user_id: str = Depends(get_current_user)):
    doc = {"id": f"nt_{uuid.uuid4().hex[:12]}", "user_id": user_id, "project_id": project_id, "title": payload.title, "content": payload.content, "folder": payload.folder, "extension": payload.extension, "created_at": _now(), "updated_at": _now()}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SUPABASE_URL}/rest/v1/files", json=doc, headers=supa_headers())
        return {"file": r.json()[0]}

@app.put("/api/v1/projects/{project_id}/files/{file_id}")
async def update_file(project_id: str, file_id: str, payload: FilePatch, user_id: str = Depends(get_current_user)):
    updates = {"updated_at": _now()}
    if payload.title is not None: updates["title"] = payload.title
    if payload.content is not None: updates["content"] = payload.content
    if payload.folder is not None: updates["folder"] = payload.folder
    if payload.extension is not None: updates["extension"] = payload.extension

    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{SUPABASE_URL}/rest/v1/files?id=eq.{file_id}&project_id=eq.{project_id}", json=updates, headers=supa_headers())
        return {"file": r.json()[0] if r.status_code == 200 and len(r.json()) > 0 else {}}

@app.delete("/api/v1/projects/{project_id}/files/{file_id}")
async def delete_file(project_id: str, file_id: str, user_id: str = Depends(get_current_user)):
    async with httpx.AsyncClient() as client:
        await client.delete(f"{SUPABASE_URL}/rest/v1/files?id=eq.{file_id}&project_id=eq.{project_id}", headers=supa_headers())
        return {"status": "deleted"}

@app.get("/api/v1/workspace/calendar")
async def google_calendar(x_google_token: Annotated[Optional[str], Header()] = None):
    if not x_google_token: return {"sync_status": "unlinked", "events": []}
    
    url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin={_now()}&maxResults=20&singleEvents=true&orderBy=startTime"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {x_google_token}"})
    
    if resp.status_code == 200:
        events = [{"title": i.get("summary", "Event"), "start_time": i.get("start", {}).get("dateTime"), "description": i.get("description", "")} for i in resp.json().get("items", [])]
        return {"sync_status": "active", "events": events}
    return {"sync_status": "error", "events": []}

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "")
    return {"response": f"Vex AI: I hear you saying '{message}'. (Backend LLM integration pending)"}