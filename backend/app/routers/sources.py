from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend.app.services.workbench import *

router = APIRouter()

@router.get("/api/v1/ocr/engines")
def list_ocr_engines() -> list[dict[str, str]]:
    available = get_available_engines()
    return [
        {
            "engine_id": engine_id,
            "label": engine.label
        }
        for engine_id, engine in available.items()
    ]


@router.get("/api/v1/sources")
def sources() -> list[dict[str, Any]]:
    if not get_sources_path().exists():
        return []
    manifests = ocr_manifests_by_source()
    records = load_json(get_sources_path())
    for record in records:
        manifest = manifests.get(record["source_id"])
        record["ocr_status"] = manifest["status"] if manifest else "not_started"
        record["ocr_pages"] = manifest.get("pages", []) if manifest else []
    return records


@router.get("/api/v1/ocr/runs")
def ocr_runs() -> list[dict[str, Any]]:
    return list(ocr_manifests_by_source().values())


@router.get("/api/v1/ocr/runs/{source_id}")
def ocr_run(source_id: str) -> dict[str, Any]:
    manifest_path = get_ocr_raw_dir() / source_id / "manifest.json"
    if not manifest_path.exists():
        manifest_path = get_ocr_manual_dir() / source_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="OCR run not found")
    manifest = load_json(manifest_path)
    pages = []
    for relative_path in manifest.get("page_json", []):
        page_path = resolve_project_relative_path(relative_path)
        pages.append(load_json(page_path))
    return {"manifest": manifest, "pages": pages}


@router.get("/api/v1/reading/sources")
def reading_sources(
    query: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    include_pdf_diagnostics: bool = False,
) -> list[dict[str, Any]]:
    records = load_sources()
    sources = []
    for record in records:
        if query:
            haystack = " ".join(
                [
                    record.get("source_id", ""),
                    record.get("title", ""),
                    record.get("title_original", ""),
                    record.get("collection", ""),
                    record.get("category", ""),
                    record.get("local_pdf", ""),
                ]
            ).lower()
            if query.lower() not in haystack:
                continue
        sources.append(enrich_reading_source(record, include_pdf_diagnostics=include_pdf_diagnostics))
        if limit and len(sources) >= limit:
            break
    return sources


@router.post("/api/v1/reading/import-pdf")
async def import_reading_pdf(request: Request) -> dict[str, Any]:
    filename = unquote(request.headers.get("x-filename") or "imported.pdf")
    data = await request.body()
    
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                image_infos = [info for info in z.infolist() if info.filename.lower().endswith((".png", ".jpg", ".jpeg"))]
                if not image_infos:
                    raise HTTPException(status_code=400, detail="No images found in zip")
                
                image_infos.sort(key=lambda info: info.date_time)
                
                from PIL import Image
                images = []
                for info in image_infos:
                    img_data = z.read(info)
                    img = Image.open(io.BytesIO(img_data)).convert("RGB")
                    images.append(img)
                
                pdf_bytes = io.BytesIO()
                images[0].save(pdf_bytes, format="PDF", save_all=True, append_images=images[1:])
                data = pdf_bytes.getvalue()
                filename = filename[:-4] + ".pdf"
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")

    result = upsert_imported_source(filename, data)
    source = result["source"]
    diagnostics = pdf_diagnostics(source_by_id(source["source_id"]), page=1, render=True)
    source["pdf_status"] = diagnostics
    render_message = "Page 1 rendered successfully." if diagnostics.get("renderable") else diagnostics.get("diagnostic_error", "Page 1 could not render.")
    return {
        "ok": True,
        "created": result["created"],
        "source": source,
        "diagnostics": diagnostics,
        "message": (
            f"Imported local PDF into the ignored raw folder. {render_message}"
            if result["created"]
            else f"PDF was already in the source catalog. {render_message}"
        ),
    }


@router.get("/api/v1/reading/sources/{source_id}/diagnostics")
def reading_source_diagnostics(source_id: str, page: int | None = None) -> dict[str, Any]:
    return pdf_diagnostics(source_by_id(source_id), page=page, render=page is not None)


@router.delete("/api/v1/reading/sources/{source_id}")
def delete_reading_source(source_id: str) -> dict[str, Any]:
    sources_path = get_sources_path()
    if not sources_path.exists():
        raise HTTPException(status_code=404, detail="Sources catalog not found")
    
    records = load_json(sources_path)
    target_record = None
    updated_records = []
    
    for r in records:
        if r.get("source_id") == source_id:
            target_record = r
        else:
            updated_records.append(r)
            
    if not target_record:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found in catalog")
        
    # Write back the updated catalog
    write_json(sources_path, updated_records)
    
    # Delete raw local PDF if it exists
    try:
        pdf_file = raw_pdf_path(target_record)
        if pdf_file.exists():
            pdf_file.unlink()
    except Exception:
        pass
        
    # Delete OCR outputs if they exist
    try:
        raw_ocr_dir = get_ocr_raw_dir() / source_id
        if raw_ocr_dir.exists():
            import shutil
            shutil.rmtree(raw_ocr_dir)
        manual_ocr_dir = get_ocr_manual_dir() / source_id
        if manual_ocr_dir.exists():
            import shutil
            shutil.rmtree(manual_ocr_dir)
        corrected_ocr_dir = get_ocr_corrected_dir() / source_id
        if corrected_ocr_dir.exists():
            import shutil
            shutil.rmtree(corrected_ocr_dir)
        regions_ocr_dir = get_ocr_regions_dir() / source_id
        if regions_ocr_dir.exists():
            import shutil
            shutil.rmtree(regions_ocr_dir)
        work_ocr_dir = get_ocr_work_dir() / "region-ocr" / source_id
        if work_ocr_dir.exists():
            import shutil
            shutil.rmtree(work_ocr_dir)
    except Exception:
        pass
        
    return {"ok": True, "message": f"Source {source_id} deleted successfully."}
