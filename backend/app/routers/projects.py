from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import backend.app.services.workbench as wb

router = APIRouter()

@router.get("/api/v1/projects")
def list_projects() -> dict[str, Any]:
    projects = ["default"]
    projects_dir = wb.ROOT / "projects"
    if projects_dir.exists() and projects_dir.is_dir():
        for p in projects_dir.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                projects.append(p.name)
    return {"projects": projects, "active": wb.ACTIVE_PROJECT_ID}


@router.post("/api/v1/projects")
async def create_project(request: Request) -> dict[str, Any]:
    data = await request.json()
    project_name = data.get("name", "").strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="Project name is required")
    project_id = re.sub(r"[^A-Za-z0-9_-]+", "_", project_name).lower()
    if not project_id:
        raise HTTPException(status_code=400, detail="Invalid project name")
    
    project_dir = wb.ROOT / "projects" / project_id
    if project_dir.exists():
        raise HTTPException(status_code=400, detail="Project already exists")
    
    for sub in [
        Path("db"),
        Path("sources") / "metadata",
        Path("artifacts") / "extractions",
        Path("artifacts") / "ocr" / "raw",
        Path("artifacts") / "ocr" / "manual",
        Path("artifacts") / "ocr" / "corrected",
        Path("artifacts") / "ocr" / "regions",
        Path("artifacts") / "ocr" / "table-review",
        Path("artifacts") / "ocr" / "work",
        Path("artifacts") / "review" / "batch-biographies",
    ]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    
    sources_path = project_dir / "sources" / "metadata" / "sources.json"
    sources_path.write_text("[]\n", encoding="utf-8")
    
    old_project_id = wb.ACTIVE_PROJECT_ID
    try:
        wb.ACTIVE_PROJECT_ID = project_id
        # wb.run_workspace_script("build_database.py")
        pass
    finally:
        wb.ACTIVE_PROJECT_ID = old_project_id
    
    return {"ok": True, "project_id": project_id}


@router.get("/api/v1/projects/active")
def get_active_project_endpoint() -> dict[str, Any]:
    return {"active": wb.ACTIVE_PROJECT_ID}


@router.post("/api/v1/projects/active")
async def set_active_project_endpoint(request: Request) -> dict[str, Any]:
    data = await request.json()
    project_id = data.get("project_id", "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if project_id != "default" and not (wb.ROOT / "projects" / project_id).exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    wb.ACTIVE_PROJECT_ID = project_id
    wb.set_active_project(project_id)
    return {"ok": True, "active": wb.ACTIVE_PROJECT_ID}


@router.delete("/api/v1/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    if project_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default project")
    
    project_dir = wb.ROOT / "projects" / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_dir = wb.ROOT / "projects" / f".deleted_{project_id}_{timestamp}"
    try:
        project_dir.rename(archive_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to archive project directory: {exc}")
        
    if wb.ACTIVE_PROJECT_ID == project_id:
        wb.ACTIVE_PROJECT_ID = "default"
        wb.set_active_project("default")
        
    return {"ok": True, "message": f"Project archived as {archive_dir.name}"}


@router.post("/api/v1/projects/import")
async def import_project(request: Request, name: str = Query(...)) -> dict[str, Any]:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")
    
    project_id = re.sub(r"[^A-Za-z0-9_-]+", "_", name).lower()
    if not project_id:
        raise HTTPException(status_code=400, detail="Invalid project name")
        
    project_dir = wb.ROOT / "projects" / project_id
    if project_dir.exists():
        raise HTTPException(status_code=400, detail="Project already exists")
        
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")
        
    if isinstance(data, dict):
        if "source_id" in data:
            data = [data]
        elif "sources" in data and isinstance(data["sources"], list):
            data = data["sources"]
        else:
            raise HTTPException(status_code=400, detail="JSON must be a list of sources or a source object")
    elif not isinstance(data, list):
        raise HTTPException(status_code=400, detail="JSON must be a list of sources or a source object")
        
    for sub in [
        Path("db"),
        Path("sources") / "metadata",
        Path("artifacts") / "extractions",
        Path("artifacts") / "ocr" / "raw",
        Path("artifacts") / "ocr" / "manual",
        Path("artifacts") / "ocr" / "corrected",
        Path("artifacts") / "ocr" / "regions",
        Path("artifacts") / "ocr" / "table-review",
        Path("artifacts") / "ocr" / "work",
        Path("artifacts") / "review" / "batch-biographies",
    ]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
        
    sources_path = project_dir / "sources" / "metadata" / "sources.json"
    wb.write_json(sources_path, data)
    
    old_project_id = wb.ACTIVE_PROJECT_ID
    try:
        wb.ACTIVE_PROJECT_ID = project_id
        # wb.run_workspace_script("build_database.py")
        pass
    finally:
        wb.ACTIVE_PROJECT_ID = old_project_id
        
    return {"ok": True, "project_id": project_id}


@router.post("/api/v1/projects/{project_id}/rename")
async def rename_project(project_id: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    new_name = payload.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New project name is required")
    new_project_id = re.sub(r"[^A-Za-z0-9_-]+", "_", new_name).lower()
    if not new_project_id:
        raise HTTPException(status_code=400, detail="Invalid project name")
        
    old_dir = wb.ROOT / "projects" / project_id
    new_dir = wb.ROOT / "projects" / new_project_id
    if not old_dir.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")
    if new_dir.exists() and new_project_id != project_id:
        raise HTTPException(status_code=400, detail="A project with that name already exists")
        
    if new_project_id != project_id:
        old_dir.rename(new_dir)
        
    if wb.ACTIVE_PROJECT_ID == project_id:
        wb.ACTIVE_PROJECT_ID = new_project_id
        wb.set_active_project(new_project_id)
        
    return {"ok": True, "project_id": new_project_id}


@router.put("/api/v1/sources/{source_id}/metadata")
async def update_source_metadata(source_id: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    
    # Update in extractions artifact JSON if it exists
    artifact = wb.reading_extraction_artifact(source_id)
    artifact["title"] = payload.get("title", artifact.get("title", ""))
    artifact["title_original"] = payload.get("title_original", artifact.get("title_original", ""))
    artifact["citation"] = payload.get("citation", artifact.get("citation", ""))
    artifact["collection"] = payload.get("collection", artifact.get("collection", ""))
    artifact["notes"] = payload.get("notes", artifact.get("notes", ""))
    wb.save_reading_extraction_artifact(source_id, artifact)
    
    # Also update in project sources.json if it exists
    sources_json_path = wb.get_sources_path()
    if sources_json_path.exists():
        sources_list = wb.load_json(sources_json_path)
        updated = False
        for s in sources_list:
            if s.get("source_id") == source_id:
                s["title"] = payload.get("title", s.get("title", ""))
                s["title_original"] = payload.get("title_original", s.get("title_original", ""))
                s["citation"] = payload.get("citation", s.get("citation", ""))
                s["collection"] = payload.get("collection", s.get("collection", ""))
                s["notes"] = payload.get("notes", s.get("notes", ""))
                updated = True
                break
        if updated:
            wb.write_json(sources_json_path, sources_list)
            
    return {"ok": True, "message": "Source metadata updated successfully"}


@router.get("/api/v1/projects/{project_id}/note")
def get_project_note(project_id: str) -> dict[str, Any]:
    if project_id == "default":
        note_path = wb.ROOT / "db" / "project_note.txt"
    else:
        note_path = wb.ROOT / "projects" / project_id / "project_note.txt"
    
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_content = ""
    if note_path.exists():
        note_content = note_path.read_text(encoding="utf-8")
    
    return {"project_id": project_id, "note": note_content}


@router.put("/api/v1/projects/{project_id}/note")
async def update_project_note(project_id: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    note_content = payload.get("note", "")
    
    if project_id == "default":
        note_path = wb.ROOT / "db" / "project_note.txt"
    else:
        note_path = wb.ROOT / "projects" / project_id / "project_note.txt"
        
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(note_content, encoding="utf-8")
    
    return {"ok": True}

