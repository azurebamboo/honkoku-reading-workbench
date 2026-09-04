from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import (
    sources,
    reading,
    batch_ocr,
    projects,
)
from backend.app.services.workbench import load_env


load_env()

app = FastAPI(title="Koshu Standalone OCR & Reading Desk API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    sources.router,
    reading.router,
    batch_ocr.router,
    projects.router,
):
    app.include_router(router)


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "app": "standalone-ocr-reading-desk",
    }

import sys
from pathlib import Path
from fastapi.responses import FileResponse

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BUNDLE_ROOT = Path(sys._MEIPASS)
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent.parent.parent

@app.get("/")
def read_root():
    index_path = BUNDLE_ROOT / "frontend" / "dist" / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Koshu Standalone OCR backend is running. Build the frontend to view the Workbench UI."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

