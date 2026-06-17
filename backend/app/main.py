from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import (
    sources,
    reading,
    batch_ocr,
)
from backend.app.services.workbench import load_env


load_env()

app = FastAPI(title="Koshu Standalone OCR & Reading Desk API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    sources.router,
    reading.router,
    batch_ocr.router,
):
    app.include_router(router)


@app.get("/api/v1/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "app": "standalone-ocr-reading-desk",
    }
