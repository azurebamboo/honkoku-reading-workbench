from __future__ import annotations

import json
import hashlib
import csv
import io
import re
import sqlite3
import zipfile
import subprocess
import sys
import tempfile
import threading
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend.app.services.worker_ai import analyze_page_with_worker, worker_config_from_env


if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BUNDLE_ROOT = Path(sys._MEIPASS)
else:
    BUNDLE_ROOT = Path(__file__).resolve().parents[3]

if getattr(sys, 'frozen', False):
    exe_dir = Path(sys.executable).parent
    if exe_dir.name == "koshu-ocr-backend" and exe_dir.parent.name == "dist":
        DATA_ROOT = exe_dir.parent.parent
    else:
        DATA_ROOT = exe_dir
else:
    DATA_ROOT = Path(__file__).resolve().parents[3]

ROOT = DATA_ROOT
NDLOCR_VENDOR_DIR = BUNDLE_ROOT / "tools" / "vendor" / "ndlocr-lite"
EDITABLE_EXTRACTION_SOURCE_IDS = {"raw_ee2029d2f4ef", "raw_8ab4cdc4678e"}

ACTIVE_PROJECT_FILE = DATA_ROOT / "db" / "active_project.txt"
_pdf_render_lock = threading.RLock()

def is_testing_environment() -> bool:
    import sys
    for arg in sys.argv:
        arg_lower = arg.lower()
        if "unittest" in arg_lower or "pytest" in arg_lower or "test_reading_analysis" in arg_lower:
            return True
    return False

def get_active_project() -> str:
    if is_testing_environment():
        return "default"
    if ACTIVE_PROJECT_FILE.exists():
        try:
            return ACTIVE_PROJECT_FILE.read_text(encoding="utf-8").strip() or "default"
        except Exception:
            return "default"
    return "default"

ACTIVE_PROJECT_ID = get_active_project()

def get_project_dir() -> Path:
    if is_testing_environment() or ACTIVE_PROJECT_ID == "default":
        return ROOT
    else:
        return ROOT / "projects" / ACTIVE_PROJECT_ID

def get_db_path() -> Path:
    return get_project_dir() / "db" / "koshu.sqlite"

def get_sources_path() -> Path:
    return get_project_dir() / "sources" / "metadata" / "sources.json"

def resolve_project_relative_path(path_val: str | Path | None) -> Path | None:
    if not path_val:
        return None
    path_obj = Path(path_val)
    if path_obj.is_absolute():
        return path_obj
    
    parts = path_obj.parts
    if len(parts) > 2 and parts[0] == "projects":
        sub_path = Path(*parts[2:])
        proj_path = get_project_dir() / sub_path
        if proj_path.exists():
            return proj_path
            
    proj_path = get_project_dir() / path_obj
    if proj_path.exists():
        return proj_path
    root_path = ROOT / path_obj
    return root_path

def to_project_relative_path(path_val: Path | str) -> str:
    path_obj = Path(path_val).resolve()
    try:
        return path_obj.relative_to(get_project_dir().resolve()).as_posix()
    except ValueError:
        return path_obj.relative_to(ROOT.resolve()).as_posix()


def normalize_project_path(path_val: str | Path | None) -> str:
    if not path_val:
        return ""
    resolved = resolve_project_relative_path(path_val)
    if resolved:
        return to_project_relative_path(resolved)
    return str(path_val)


# Module-level paths for backwards compatibility and unit test patching
OCR_RAW_DIR = ROOT / "artifacts" / "ocr" / "raw"
OCR_MANUAL_DIR = ROOT / "artifacts" / "ocr" / "manual"
OCR_CORRECTED_DIR = ROOT / "artifacts" / "ocr" / "corrected"
OCR_REGIONS_DIR = ROOT / "artifacts" / "ocr" / "regions"
TABLE_REVIEW_DIR = ROOT / "artifacts" / "ocr" / "table-review"
OCR_WORK_DIR = ROOT / "artifacts" / "ocr" / "work"
BATCH_REVIEW_DIR = ROOT / "artifacts" / "review" / "batch-biographies"
EXTRACTIONS_DIR = ROOT / "artifacts" / "extractions"


def get_extractions_dir() -> Path:
    if EXTRACTIONS_DIR != ROOT / "artifacts" / "extractions":
        return EXTRACTIONS_DIR
    return get_project_dir() / "artifacts" / "extractions"

def get_ocr_raw_dir() -> Path:
    if OCR_RAW_DIR != ROOT / "artifacts" / "ocr" / "raw":
        return OCR_RAW_DIR
    return get_project_dir() / "artifacts" / "ocr" / "raw"

def get_ocr_manual_dir() -> Path:
    if OCR_MANUAL_DIR != ROOT / "artifacts" / "ocr" / "manual":
        return OCR_MANUAL_DIR
    return get_project_dir() / "artifacts" / "ocr" / "manual"

def get_ocr_corrected_dir() -> Path:
    if OCR_CORRECTED_DIR != ROOT / "artifacts" / "ocr" / "corrected":
        return OCR_CORRECTED_DIR
    return get_project_dir() / "artifacts" / "ocr" / "corrected"

def get_ocr_regions_dir() -> Path:
    if OCR_REGIONS_DIR != ROOT / "artifacts" / "ocr" / "regions":
        return OCR_REGIONS_DIR
    return get_project_dir() / "artifacts" / "ocr" / "regions"

def get_table_review_dir() -> Path:
    if TABLE_REVIEW_DIR != ROOT / "artifacts" / "ocr" / "table-review":
        return TABLE_REVIEW_DIR
    return get_project_dir() / "artifacts" / "ocr" / "table-review"

def get_ocr_work_dir() -> Path:
    if OCR_WORK_DIR != ROOT / "artifacts" / "ocr" / "work":
        return OCR_WORK_DIR
    return get_project_dir() / "artifacts" / "ocr" / "work"

def get_batch_review_dir() -> Path:
    if BATCH_REVIEW_DIR != ROOT / "artifacts" / "review" / "batch-biographies":
        return BATCH_REVIEW_DIR
    return get_project_dir() / "artifacts" / "review" / "batch-biographies"


def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    os.environ[key] = val


load_env()


def get_available_engines() -> dict[str, Any]:
    from backend.app.core.providers import (
        NDLOCREngine,
        VisionLLMOCREngine,
        MineruOCREngine,
        PaddleOCREngine
    )
    engines = {
        "ndlocr_lite": NDLOCREngine()
    }
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        model = os.getenv("GEMINI_MODEL")
        engines["vision_llm_gemini"] = VisionLLMOCREngine("gemini", gemini_key, model)
        
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        model = os.getenv("OPENAI_MODEL")
        engines["vision_llm_openai"] = VisionLLMOCREngine("openai", openai_key, model)
        
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        model = os.getenv("ANTHROPIC_MODEL")
        engines["vision_llm_anthropic"] = VisionLLMOCREngine("anthropic", anthropic_key, model)
        
    mineru_key = os.getenv("MINERU_API_KEY")
    if mineru_key:
        model = os.getenv("MINERU_MODEL") or "vlm"
        api_url = os.getenv("MINERU_API_URL") or "https://mineru.net"
        engines["mineru"] = MineruOCREngine(mineru_key, api_url, model)

    paddleocr_key = os.getenv("PADDLEOCR_API_KEY")
    if paddleocr_key:
        paddleocr_url = os.getenv("PADDLEOCR_API_URL") or "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
        paddleocr_model = os.getenv("PADDLEOCR_MODEL") or "PaddleOCR-VL-1.6"
        engines["paddleocr"] = PaddleOCREngine(paddleocr_key, paddleocr_url, paddleocr_model)

    return engines


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def slugify(value: str, fallback: str = "item") -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if ascii_slug:
        return ascii_slug[:48]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{fallback}_{digest}"


def connect() -> sqlite3.Connection:
    if not get_db_path().exists():
        raise HTTPException(
            status_code=503,
            detail="Database is not built yet. Run `python3 scripts/build_database.py`.",
        )
    connection = sqlite3.connect(get_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def maybe_json(value: str | None) -> Any:
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def ocr_manifests_by_source() -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for root in (get_ocr_raw_dir(), get_ocr_manual_dir(), get_ocr_corrected_dir()):
        for path in sorted(root.glob("*/manifest.json")):
            manifest = load_json(path)
            manifests[manifest["source_id"]] = manifest
    return manifests


def lightweight_pdf_status(record: dict[str, Any], page_count: int | None = None) -> dict[str, Any]:
    pdf_path = raw_pdf_path(record)
    relative_path = ""
    try:
        relative_path = pdf_path.relative_to(ROOT).as_posix()
    except ValueError:
        relative_path = str(pdf_path)
    exists = pdf_path.exists()
    return {
        "source_id": record["source_id"],
        "local_pdf": record.get("local_pdf", ""),
        "local_pdf_exists": exists,
        "local_pdf_path": relative_path,
        "readable": exists,
        "page_count": page_count,
        "renderable": False,
        "diagnostic_code": "not_checked",
        "diagnostic_error": "Full PDF diagnostics are skipped in the reading source list.",
        "suggested_fix": "Open source diagnostics for a full render check.",
    }


def enrich_reading_source(record: dict[str, Any], *, include_pdf_diagnostics: bool = False) -> dict[str, Any]:
    preferred = preferred_ocr_manifest(record["source_id"])
    corrected = corrected_ocr_manifest(record["source_id"])
    preferred_manifest = preferred[1] if preferred else None
    corrected_manifest = corrected[0] if corrected else None
    pages = preferred_manifest.get("pages", []) if preferred_manifest else []
    page_count = record.get("page_count")
    if not isinstance(page_count, int) and pages:
        page_count = max(pages)
    diagnostics = pdf_diagnostics(record) if include_pdf_diagnostics else lightweight_pdf_status(record, page_count)
    page_count = diagnostics.get("page_count")
    if not pages and isinstance(page_count, int) and page_count > 0:
        pages = list(range(1, page_count + 1))
    return {
        "source_id": record["source_id"],
        "title": record.get("title", ""),
        "title_original": record.get("title_original", ""),
        "collection": record.get("collection", ""),
        "category": record.get("category", ""),
        "local_pdf": record.get("local_pdf", ""),
        "checksum_sha256": record.get("checksum_sha256", ""),
        "file_size_bytes": record.get("file_size_bytes"),
        "page_count": page_count,
        "ocr_status": preferred_manifest.get("status", "not_started") if preferred_manifest else "not_started",
        "ocr_engine": preferred_manifest.get("ocr_engine", "") if preferred_manifest else "",
        "ocr_pages": pages,
        "has_ocr": preferred_manifest is not None,
        "corrected_status": corrected_manifest.get("status", "not_started") if corrected_manifest else "not_started",
        "corrected_pages": corrected_manifest.get("pages", []) if corrected_manifest else [],
        "has_extraction": extraction_artifact_path(record["source_id"]).exists(),
        "pdf_status": diagnostics,
    }


def load_sources() -> list[dict[str, Any]]:
    if not get_sources_path().exists():
        return []
    return load_json(get_sources_path())


def source_by_id(source_id: str) -> dict[str, Any]:
    for record in load_sources():
        if record["source_id"] == source_id:
            return record
    raise HTTPException(status_code=404, detail="Source not found")


def raw_pdf_path(record: dict[str, Any]) -> Path:
    return ROOT / "sources" / "raw" / record.get("local_pdf", "")


def source_pdf_path(record: dict[str, Any]) -> Path:
    path = raw_pdf_path(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Local PDF not found: {record.get('local_pdf', '')}")
    return path


def source_pdf_reference(record: dict[str, Any]) -> str:
    return f"sources/raw/{record.get('local_pdf', '')}"


def pdf_page_count(record: dict[str, Any]) -> int | None:
    value = record.get("page_count")
    if isinstance(value, int) and value > 0:
        return value
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError:
        return None
    try:
        pdf = pdfium.PdfDocument(str(source_pdf_path(record)))
    except Exception:
        return None
    try:
        return len(pdf)
    finally:
        pdf.close()


def pdf_diagnostics(record: dict[str, Any], page: int | None = None, render: bool = False) -> dict[str, Any]:
    path = raw_pdf_path(record)
    diagnostics: dict[str, Any] = {
        "source_id": record.get("source_id", ""),
        "local_pdf": record.get("local_pdf", ""),
        "local_pdf_exists": path.exists(),
        "local_pdf_path": source_pdf_reference(record),
        "readable": False,
        "page_count": None,
        "renderable": None,
        "diagnostic_code": "",
        "diagnostic_error": "",
        "suggested_fix": "",
    }
    if not path.exists():
        diagnostics["diagnostic_code"] = "missing_raw_pdf"
        diagnostics["diagnostic_error"] = "Raw PDF is missing from sources/raw. If this file lives in cloud storage, download it locally first."
        diagnostics["suggested_fix"] = "Use Choose local PDF to import a local copy, or download the cloud-only file before opening it."
        diagnostics["renderable"] = False
        return diagnostics
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError:
        diagnostics["diagnostic_code"] = "missing_render_dependency"
        diagnostics["diagnostic_error"] = "pypdfium2 is not installed, so the workbench cannot read or render PDFs."
        diagnostics["suggested_fix"] = "Install the project environment dependencies, then restart the backend."
        diagnostics["renderable"] = False
        return diagnostics
    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            page_count = len(pdf)
        finally:
            pdf.close()
    except Exception as exc:
        diagnostics["diagnostic_code"] = "pdf_unreadable"
        diagnostics["diagnostic_error"] = f"PDF is present but unreadable: {exc}"
        diagnostics["suggested_fix"] = "Open the PDF outside the workbench to confirm it is complete, then re-import a fresh copy if needed."
        diagnostics["renderable"] = False
        return diagnostics

    diagnostics["readable"] = True
    diagnostics["page_count"] = page_count
    if page is not None and (page < 1 or page > page_count):
        diagnostics["diagnostic_code"] = "page_out_of_range"
        diagnostics["diagnostic_error"] = f"Page {page} is outside PDF page count {page_count}."
        diagnostics["suggested_fix"] = "Choose a page number inside the detected page count."
        diagnostics["renderable"] = False
        return diagnostics
    if render and page is not None:
        try:
            render_pdf_page_image(record, page)
            diagnostics["renderable"] = True
        except HTTPException as exc:
            diagnostics["diagnostic_code"] = "render_error"
            diagnostics["diagnostic_error"] = str(exc.detail)
            diagnostics["suggested_fix"] = "Try Re-render. If it still fails, re-import the PDF or check whether the file is damaged."
            diagnostics["renderable"] = False
    else:
        diagnostics["renderable"] = True
    return diagnostics


def safe_pdf_filename(filename: str, checksum: str) -> str:
    stem = Path(filename or "imported.pdf").stem.strip() or "imported"
    safe_stem = re.sub(r"[/\\:\0]+", "_", stem).strip() or "imported"
    if len(safe_stem) > 80:
        safe_stem = safe_stem[:80].rstrip()
    return f"{safe_stem}_{checksum[:12]}.pdf"


def upsert_imported_source(filename: str, data: bytes) -> dict[str, Any]:
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Choose a PDF file")
    checksum = hashlib.sha256(data).hexdigest()
    sources = load_sources()
    for record in sources:
        if record.get("checksum_sha256") == checksum:
            return {"created": False, "source": enrich_reading_source(record)}

    filename = safe_pdf_filename(filename, checksum)
    local_relative = Path("Imported PDFs") / filename
    destination = ROOT / "sources" / "raw" / local_relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    source_id = f"raw_imported_{checksum[:12]}"
    record = {
        "source_id": source_id,
        "collection": "Imported local PDFs",
        "category": "Imported",
        "repository": "",
        "call_number": "",
        "citation": "",
        "title": Path(filename).stem,
        "title_original": Path(filename).stem,
        "date": "",
        "date_certainty": "unknown",
        "language": ["ja"],
        "document_type": "pdf",
        "local_pdf": local_relative.as_posix(),
        "raw_relative_path": local_relative.as_posix(),
        "page_count": None,
        "file_size_bytes": len(data),
        "checksum_sha256": checksum,
        "external_reference": "",
        "rights_notes": "Imported locally through the Reading Desk; raw PDF is ignored by Git.",
        "inventory": {
            "inventoried_at": datetime.now(timezone.utc).isoformat(),
            "inventory_method": "Reading Desk local PDF import",
        },
    }
    record["page_count"] = pdf_page_count(record)
    sources.append(record)
    write_json(get_sources_path(), sources)
    return {"created": True, "source": enrich_reading_source(record)}


def rendered_page_image_path(source_id: str, page: int) -> Path:
    return get_ocr_work_dir() / "page-context" / source_id / f"page_{page:04d}.png"


def rendered_region_image_path(source_id: str, page: int, region_id: str) -> Path:
    return (
        ROOT
        / "artifacts"
        / "ocr"
        / "work"
        / "table-regions"
        / source_id
        / f"page_{page:04d}_{region_id}.png"
    )


def region_ocr_json_path(source_id: str, page: int, region_id: str) -> Path:
    return get_ocr_regions_dir() / source_id / "pages" / f"page_{page:04d}" / f"{region_id}.json"


def table_review_json_path(source_id: str, page: int, region_id: str) -> Path:
    return get_table_review_dir() / source_id / "pages" / f"page_{page:04d}" / f"{region_id}.json"


def external_table_review_json_path(source_id: str, page: int, import_id: str) -> Path:
    return get_table_review_dir() / source_id / "external" / f"page_{page:04d}" / f"{import_id}.json"


def sanitize_region_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned[:80] or f"reg_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:10]}"


def render_pdf_page_image(source: dict[str, Any], page: int) -> Path:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    output_path = rendered_page_image_path(source["source_id"], page)
    with _pdf_render_lock:
        if output_path.exists():
            return output_path
        try:
            import pypdfium2 as pdfium
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=500, detail="pypdfium2 is required to render page images") from exc

        pdf_path = source_pdf_path(source)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            if page > len(pdf):
                raise HTTPException(status_code=404, detail=f"Page {page} is outside PDF page count {len(pdf)}")
            bitmap = pdf[page - 1].render(scale=2.0)
            image = bitmap.to_pil()
            image.save(output_path)
        finally:
            pdf.close()
        return output_path


def rendered_rotated_page_image_path(source_id: str, page: int, rotation: int) -> Path:
    base_path = rendered_page_image_path(source_id, page)
    if not rotation:
        return base_path
    return base_path.with_name(f"{base_path.stem}_rot{rotation}{base_path.suffix}")


def render_pdf_page_image_rotated(source: dict[str, Any], page: int, rotation: int = 0) -> Path:
    with _pdf_render_lock:
        original_path = render_pdf_page_image(source, page)
        if not rotation:
            return original_path
        
        rotated_path = rendered_rotated_page_image_path(source["source_id"], page, rotation)
        if rotated_path.exists():
            return rotated_path
            
        try:
            from PIL import Image
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=500, detail="Pillow is required to rotate page images") from exc

        with Image.open(original_path) as img:
            rotated_img = img.rotate(-rotation, expand=True)
            rotated_img.save(rotated_path)
        return rotated_path


def crop_page_region(
    source: dict[str, Any], page: int, region: dict[str, Any], region_id: str, rotation: int = 0
) -> Path:
    """Crop a selected page region from the rendered page image.

    Coordinates are expected as relative fractions of the rendered image:
    x, y, width, height in the range 0.0-1.0.
    """

    full_page_path = render_pdf_page_image_rotated(source, page, rotation)
    output_path = rendered_region_image_path(source["source_id"], page, region_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Pillow is required to crop page regions") from exc

    with Image.open(full_page_path) as image:
        width, height = image.size
        x = float(region.get("x", 0))
        y = float(region.get("y", 0))
        region_width = float(region.get("width", 1))
        region_height = float(region.get("height", 1))
        if (
            x < 0
            or y < 0
            or region_width <= 0
            or region_height <= 0
            or x + region_width > 1.001
            or y + region_height > 1.001
        ):
            raise HTTPException(status_code=400, detail="Region must fit within the page image")
        box = (
            max(0, round(x * width)),
            max(0, round(y * height)),
            min(width, round((x + region_width) * width)),
            min(height, round((y + region_height) * height)),
        )
        image.crop(box).save(output_path)
    return output_path


def relative_existing_path(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    resolved = resolve_project_relative_path(value)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"{label} does not exist: {value}")
    try:
        resolved.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} must stay inside the workspace") from exc
    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"{label} does not exist: {value}")
    return resolved


def run_ndlocr_on_region(crop_path: Path, source_id: str, page: int, region_id: str) -> Path:
    ndlocr_src = NDLOCR_VENDOR_DIR / "src"
    if not ndlocr_src.exists():
        raise HTTPException(status_code=500, detail=f"NDLOCR-Lite is missing at {NDLOCR_VENDOR_DIR}")

    work_dir = get_ocr_work_dir() / "region-ocr" / source_id / f"page_{page:04d}" / region_id
    image_dir = work_dir / "images"
    output_dir = work_dir / "ndlocr-output"
    image_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    ocr_input_path = image_dir / "region.png"
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Pillow is required to prepare region OCR images") from exc
    with Image.open(crop_path) as image:
        image.save(ocr_input_path)

    # Dynamic import and execution
    if str(ndlocr_src) not in sys.path:
        sys.path.insert(0, str(ndlocr_src))
    from ocr import process as run_ocr_process

    import argparse
    args = argparse.Namespace(
        sourcedir=str(image_dir),
        sourceimg=None,
        output=str(output_dir),
        viz=False,
        det_weights=str(ndlocr_src / "model" / "deim-s-1024x1024.onnx"),
        det_classes=str(ndlocr_src / "config" / "ndl.yaml"),
        det_score_threshold=0.2,
        det_conf_threshold=0.25,
        det_iou_threshold=0.2,
        simple_mode=False,
        rec_weights30=str(ndlocr_src / "model" / "parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx"),
        rec_weights50=str(ndlocr_src / "model" / "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"),
        rec_weights=str(ndlocr_src / "model" / "parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx"),
        rec_classes=str(ndlocr_src / "config" / "NDLmoji.yaml"),
        device="cpu",
        enable_tcy=False,
        json_only=True
    )

    # Register activity
    try:
        import asyncio
        from backend.app.core.providers import _register_ocr_activity
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_register_ocr_activity())
        except RuntimeError:
            pass
    except Exception:
        pass

    try:
        run_ocr_process(args)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"NDLOCR-Lite failed: {exc}") from exc

    expected = output_dir / "region.json"
    if expected.exists():
        return expected
    outputs = sorted(output_dir.glob("*.json"))
    if outputs:
        return outputs[0]
    raise HTTPException(status_code=500, detail="NDLOCR-Lite did not produce JSON for the selected region")


def preferred_ocr_manifest(source_id: str) -> tuple[str, dict[str, Any], Path] | None:
    for label, root in (("manual", get_ocr_manual_dir()), ("raw", get_ocr_raw_dir())):
        path = root / source_id / "manifest.json"
        if path.exists():
            return label, load_json(path), path
    return None


def corrected_ocr_manifest(source_id: str) -> tuple[dict[str, Any], Path] | None:
    path = get_ocr_corrected_dir() / source_id / "manifest.json"
    if path.exists():
        return load_json(path), path
    return None


def page_json_path_for(manifest: dict[str, Any], page: int) -> str | None:
    for manifest_page, relative_path in zip(manifest.get("pages", []), manifest.get("page_json", [])):
        if manifest_page == page:
            return relative_path
    return None


def ocr_paths_for_request(source_id: str, page: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    preferred = preferred_ocr_manifest(source_id)
    raw_page_json_path = ""
    raw_manifest: dict[str, Any] | None = None
    raw_manifest_path: Path | None = None
    if preferred:
        _, raw_manifest, raw_manifest_path = preferred
        raw_page_json_path = page_json_path_for(raw_manifest, page) or ""

    corrected_page_json_path = ""
    corrected_info = corrected_ocr_manifest(source_id)
    if corrected_info:
        corrected_page_json_path = page_json_path_for(corrected_info[0], page) or ""

    raw_page_json_path = (
        raw_page_json_path
        or payload.get("ocr_page_json")
        or payload.get("region_ocr_json")
        or payload.get("original_ocr_page_json")
        or ""
    )
    corrected_page_json_path = corrected_page_json_path or payload.get("corrected_ocr_page_json") or ""
    effective_ocr_path = corrected_page_json_path or raw_page_json_path
    return {
        "raw_page_json_path": raw_page_json_path,
        "corrected_page_json_path": corrected_page_json_path,
        "effective_ocr_path": effective_ocr_path,
        "raw_manifest": raw_manifest,
        "raw_manifest_path": raw_manifest_path,
    }


def require_existing_ocr_path(path: str, label: str = "OCR provenance path") -> None:
    if not path:
        raise HTTPException(
            status_code=400,
            detail=f"Missing {label}. Run OCR or save OCR correction before saving evidence.",
        )
    resolved = resolve_project_relative_path(path)
    if not resolved or not resolved.exists():
        raise HTTPException(status_code=400, detail=f"{label} does not exist: {path}")


def flatten_ocr_text(page_json: dict[str, Any]) -> str:
    lines: list[str] = []
    for block in page_json.get("contents", []):
        if isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                lines.append(text.strip())
            continue
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        lines.append(text.strip())
    return "\n".join(lines)


def draft_table_rows_from_text(text: str) -> list[dict[str, Any]]:
    rows = []
    for index, line in enumerate([line.strip() for line in text.splitlines() if line.strip()], start=1):
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
        elif re.search(r"\s{2,}", line):
            cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        else:
            cells = [line]
        rows.append(
            {
                "row_id": f"row_{index:03d}",
                "cells": [
                    {
                        "column_id": f"col_{column_index:03d}",
                        "text": cell,
                        "review_status": "needs_review",
                    }
                    for column_index, cell in enumerate(cells, start=1)
                ],
                "source_line": line,
                "review_status": "needs_review",
            }
        )
    return rows


def table_columns_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    count = max((len(row.get("cells", [])) for row in rows), default=0)
    return [
        {
            "column_id": f"col_{index:03d}",
            "label": f"Column {index}",
            "review_status": "needs_review",
        }
        for index in range(1, count + 1)
    ]


def table_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    column_count = max((len(row.get("cells", [])) for row in rows), default=0)
    if column_count == 0:
        return ""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"column_{index:03d}" for index in range(1, column_count + 1)])
    for row in rows:
        cells = [cell.get("text", "") for cell in row.get("cells", [])]
        writer.writerow(cells + [""] * (column_count - len(cells)))
    return buffer.getvalue()


def table_rows_to_markdown(rows: list[dict[str, Any]]) -> str:
    column_count = max((len(row.get("cells", [])) for row in rows), default=0)
    if column_count == 0:
        return ""
    headers = [f"Column {index}" for index in range(1, column_count + 1)]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * column_count) + " |",
    ]
    for row in rows:
        cells = [str(cell.get("text", "")).replace("|", "\\|") for cell in row.get("cells", [])]
        cells.extend([""] * (column_count - len(cells)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def rows_from_csv_text(csv_text: str) -> list[dict[str, Any]]:
    if not csv_text.strip():
        return []
    reader = csv.reader(io.StringIO(csv_text))
    rows = []
    parsed = list(reader)
    if not parsed:
        return rows
    data_rows = parsed[1:] if len(parsed) > 1 else parsed
    for row_index, row in enumerate(data_rows, start=1):
        if not any(cell.strip() for cell in row):
            continue
        rows.append(
            {
                "row_id": f"external_row_{row_index:03d}",
                "cells": [
                    {
                        "column_id": f"col_{column_index:03d}",
                        "text": cell.strip(),
                        "review_status": "needs_review",
                    }
                    for column_index, cell in enumerate(row, start=1)
                ],
                "source_line": ",".join(row),
                "review_status": "needs_review",
            }
        )
    return rows


def extraction_artifact_path(source_id: str) -> Path:
    return get_extractions_dir() / f"{source_id}.json"


def officer_table_artifact_id(source_id: str, page: int, table_title: str = "") -> str:
    if source_id == "raw_f344c3ccb490" and page == 15:
        return "chihou_zaibatsu_p324_katsuragawa_officers"
    suffix = slugify(table_title, "officers") if table_title else "officers"
    return f"officer_table_{source_id}_p{page:04d}_{suffix}"


def officer_table_artifact_path(source_id: str, page: int, table_title: str = "") -> Path:
    return get_extractions_dir() / f"{officer_table_artifact_id(source_id, page, table_title)}.json"


def editable_extraction_artifact(source_id: str) -> dict[str, Any]:
    path = extraction_artifact_path(source_id)
    if not path.exists():
        try:
            source_by_id(source_id)
            return reading_extraction_artifact(source_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Extraction artifact and source not found")
    artifact = load_json(path)
    if artifact.get("provenance", {}).get("status") != "draft":
        raise HTTPException(status_code=403, detail="Only draft artifacts are editable")
    if artifact.get("extraction_schema_version") != "evidence-graph-v1":
        raise HTTPException(status_code=403, detail="Only evidence graph artifacts are editable")
    return artifact


def validate_extraction_candidate(source_id: str, artifact: dict[str, Any]) -> None:
    if artifact.get("source_id") != source_id:
        raise HTTPException(status_code=400, detail="Artifact source_id must match URL source_id")
    if artifact.get("provenance", {}).get("status") != "draft":
        raise HTTPException(status_code=400, detail="Edited artifact must remain draft")
    if artifact.get("extraction_schema_version") != "evidence-graph-v1":
        raise HTTPException(status_code=400, detail="Edited artifact must use evidence-graph-v1")

    old_project = os.environ.get("KOSHU_PROJECT")
    os.environ["KOSHU_PROJECT"] = ACTIVE_PROJECT_ID

    try:
        try:
            from scripts.validate_extractions import validate_artifact
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not load validator: {exc}") from exc

        with tempfile.TemporaryDirectory(prefix="koshu-extraction-validate-") as temp_dir:
            candidate_path = Path(temp_dir) / f"{source_id}.json"
            candidate_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            errors = validate_artifact(candidate_path)
    finally:
        if old_project is not None:
            os.environ["KOSHU_PROJECT"] = old_project
        else:
            os.environ.pop("KOSHU_PROJECT", None)

    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})


def run_workspace_script(script_name: str) -> None:
    # Set the environment variable so the script picks it up in the same process
    os.environ["KOSHU_PROJECT"] = ACTIVE_PROJECT_ID
    
    script_path = BUNDLE_ROOT / "scripts" / script_name
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"Script {script_name} not found")
        
    try:
        import importlib.util
        # Dynamically load the script as a module
        spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), str(script_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load spec for {script_name}")
        module = importlib.util.module_from_spec(spec)
        
        # Add scripts directory to path if not already there
        scripts_dir = str(BUNDLE_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            
        spec.loader.exec_module(module)
        
        # If it has a main entry point, run it
        if hasattr(module, "main"):
            ret = module.main()
            if ret is not None and ret != 0:
                raise RuntimeError(f"Script returned non-zero exit code: {ret}")
                
    except Exception as exc:
        import traceback
        detail = f"{script_name} failed: {exc}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=detail) from exc


def reading_extraction_artifact(source_id: str) -> dict[str, Any]:
    path = extraction_artifact_path(source_id)
    if path.exists():
        artifact = load_json(path)
        if artifact.get("extraction_schema_version") != "evidence-graph-v1":
            raise HTTPException(status_code=400, detail="Reading Desk requires an evidence-graph-v1 artifact")
        # Normalize paths in existing evidence_quotes
        for evidence in artifact.get("evidence_quotes", []):
            for key in ("ocr_page_json", "raw_ocr_page_json", "corrected_ocr_page_json"):
                if key in evidence and evidence[key]:
                    evidence[key] = normalize_project_path(evidence[key])
        return artifact

    source = source_by_id(source_id)
    pages: list[int] = []
    manifest_info = preferred_ocr_manifest(source_id)
    if manifest_info:
        pages = manifest_info[1].get("pages", [])
    page_end = max(pages) if pages else int(pdf_page_count(source) or 1)
    return {
        "source_id": source_id,
        "collection": source.get("collection", ""),
        "citation": source.get("citation", ""),
        "title": source.get("title", ""),
        "title_original": source.get("title_original", ""),
        "date": source.get("date", ""),
        "date_certainty": source.get("date_certainty", "unknown"),
        "language": source.get("language", ["ja"]),
        "document_type": source.get("document_type", "pdf"),
        "local_pdf": source_pdf_reference(source),
        "external_reference": source.get("external_reference", ""),
        "summary_en": "",
        "notes": "Draft evidence graph created from the Reading Desk.",
        "entities": [],
        "claims": [],
        "keywords": [],
        "provenance": {
            "status": "draft",
            "reviewer": "Reading Desk",
            "extraction_date": datetime.now(timezone.utc).date().isoformat(),
            "method": "interactive OCR review and evidence extraction",
        },
        "extraction_schema_version": "evidence-graph-v1",
        "extraction_scope": {
            "page_start": min(pages) if pages else 1,
            "page_end": page_end,
            "ocr_manifest": str((manifest_info[2].relative_to(ROOT) if manifest_info else Path("")).as_posix()),
            "status": "draft",
        },
        "entity_records": [],
        "evidence_quotes": [],
        "entity_mentions": [],
        "relationship_claims": [],
        "attitude_claims": [],
        "reading_notes": [],
    }


def save_reading_extraction_artifact(source_id: str, artifact: dict[str, Any]) -> None:
    validate_extraction_candidate(source_id, artifact)
    write_json(extraction_artifact_path(source_id), artifact)
    # run_workspace_script("validate_extractions.py")
    # run_workspace_script("build_database.py")
    pass


def include_page_in_scope(artifact: dict[str, Any], page: int) -> None:
    scope = artifact.setdefault("extraction_scope", {})
    current_start = scope.get("page_start")
    current_end = scope.get("page_end")
    scope["page_start"] = min(current_start, page) if isinstance(current_start, int) else page
    scope["page_end"] = max(current_end, page) if isinstance(current_end, int) else page


def next_id(records: list[dict[str, Any]], id_field: str, prefix: str) -> str:
    existing = {record.get(id_field) for record in records}
    index = len(existing) + 1
    while f"{prefix}_{index:03d}" in existing:
        index += 1
    return f"{prefix}_{index:03d}"


def ensure_entity(
    artifact: dict[str, Any],
    entity_id: str | None,
    name: str,
    entity_type: str,
    aliases: list[str] | None = None,
    notes: str = "",
) -> str:
    if not entity_id and not name:
        raise HTTPException(status_code=400, detail="Entity name is required")
    records = artifact.setdefault("entity_records", [])
    if entity_id and any(record.get("entity_id") == entity_id for record in records):
        return entity_id
    if entity_id:
        records.append(
            {
                "entity_id": entity_id,
                "canonical_name": name or entity_id,
                "name_original": name or entity_id,
                "entity_type": entity_type or "person",
                "aliases": aliases or [],
                "notes": notes,
            }
        )
        return entity_id
    for record in records:
        if record.get("canonical_name") == name or record.get("name_original") == name:
            return record["entity_id"]
    generated_id = f"rd_{artifact['source_id']}_ent_{slugify(name, 'entity')}"
    suffix = 2
    existing = {record.get("entity_id") for record in records}
    candidate = generated_id
    while candidate in existing:
        candidate = f"{generated_id}_{suffix}"
        suffix += 1
    records.append(
        {
            "entity_id": candidate,
            "canonical_name": name,
            "name_original": name,
            "entity_type": entity_type or "person",
            "aliases": aliases or [],
            "notes": notes,
        }
    )
    return candidate


def ensure_evidence(
    artifact: dict[str, Any],
    source: dict[str, Any],
    page: int,
    quote: str,
    ocr_page_json: str,
    corrected_ocr_page_json: str | None,
    note: str,
) -> str:
    if not quote.strip():
        raise HTTPException(status_code=400, detail="Evidence quote is required")
    evidence_quotes = artifact.setdefault("evidence_quotes", [])
    for evidence in evidence_quotes:
        if evidence.get("page") == page and evidence.get("quote") == quote:
            return evidence["evidence_id"]
    prefix = f"rd_{artifact['source_id']}_p{page:04d}_ev"
    evidence_id = next_id(evidence_quotes, "evidence_id", prefix)
    raw_path_norm = normalize_project_path(ocr_page_json)
    corrected_path_norm = normalize_project_path(corrected_ocr_page_json) if corrected_ocr_page_json else ""
    record = {
        "evidence_id": evidence_id,
        "source_id": artifact["source_id"],
        "page": page,
        "quote": quote.strip(),
        "ocr_page_json": corrected_path_norm or raw_path_norm,
        "source_pdf": source_pdf_reference(source),
        "note": note,
    }
    if corrected_path_norm:
        if raw_path_norm and raw_path_norm != corrected_path_norm:
            record["raw_ocr_page_json"] = raw_path_norm
        record["corrected_ocr_page_json"] = corrected_path_norm
    evidence_quotes.append(record)
    return evidence_id


def add_mention(
    artifact: dict[str, Any],
    entity_id: str,
    source_id: str,
    page: int,
    name_as_appears: str,
    evidence_id: str,
    confidence: str,
    note: str,
) -> None:
    mentions = artifact.setdefault("entity_mentions", [])
    if any(
        mention.get("entity_id") == entity_id
        and mention.get("page") == page
        and mention.get("name_as_appears") == name_as_appears
        and mention.get("evidence_id") == evidence_id
        for mention in mentions
    ):
        return
    mention_id = next_id(mentions, "mention_id", f"rd_{source_id}_p{page:04d}_men")
    mentions.append(
        {
            "mention_id": mention_id,
            "entity_id": entity_id,
            "source_id": source_id,
            "page": page,
            "name_as_appears": name_as_appears,
            "evidence_id": evidence_id,
            "confidence": confidence or "medium",
            "note": note,
        }
    )


def reading_vocabularies() -> dict[str, Any]:
    # Standalone fallback lists without SQLite dependencies
    return {
        "relation_types": [
            "membership", "alliance", "support", "opposition", "employment", 
            "ownership", "family_relationship", "colleague", "acquaintance", "other"
        ],
        "attitude_types": [
            "supportive", "hostile", "neutral", "critical", "suspicious", "collaborative"
        ],
        "polarities": ["positive", "negative", "neutral"],
        "entity_types": ["person", "institution", "company", "place", "publication", "political_group", "law_or_policy"],
        "confidence": ["high", "medium", "low"],
    }


def candidate_provenance(
    source_id: str,
    page: int,
    payload: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    provenance = {
        "source_id": source_id,
        "page": page,
        "ocr_page_json": payload.get("ocr_page_json") or "",
        "corrected_ocr_page_json": payload.get("corrected_ocr_page_json") or "",
        "region": payload.get("region") or {},
        "region_id": payload.get("region_id") or "",
    }
    if evidence:
        provenance["evidence_id"] = evidence.get("evidence_id", "")
        provenance["ocr_page_json"] = evidence.get("raw_ocr_page_json") or evidence.get("ocr_page_json") or provenance["ocr_page_json"]
        provenance["corrected_ocr_page_json"] = evidence.get("corrected_ocr_page_json") or provenance["corrected_ocr_page_json"]
        provenance["source_pdf"] = evidence.get("source_pdf", "")
    return provenance


def quote_candidates_from_text(source_id: str, page: int, text: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 16]
    provenance = candidate_provenance(source_id, page, payload)
    for line in lines[:12]:
        if line in seen:
            continue
        seen.add(line)
        digest = hashlib.sha1(f"{source_id}:{page}:quote:{line}".encode("utf-8")).hexdigest()[:12]
        candidates.append(
            {
                "candidate_id": f"cand_quote_{digest}",
                "candidate_type": "quote",
                "kind": "quote",
                "source_id": source_id,
                "page": page,
                "label": line,
                "quote": line,
                "confidence": "medium",
                "status": "candidate",
                "action": "Review this quote before saving",
                "provenance": provenance,
            }
        )
    return candidates


NETWORK_RELATIONSHIP_TERMS = [
    "関係",
    "取締",
    "取締役",
    "專務",
    "専務",
    "會長",
    "会長",
    "監査",
    "監察",
    "頭取",
    "社員",
    "所属",
    "協力",
    "提携",
    "対立",
    "對立",
    "批判",
    "糺",
    "膺懲",
    "支持",
    "反対",
    "反對",
    "告訴",
    "訴訟",
    "證言",
    "証言",
    "公開状",
    "創立",
    "設立",
    "銀行",
    "会社",
    "社",
    "鉄道",
    "電力",
    "電灯",
    "炭鉱",
    "employment",
    "affiliation",
    "cooperation",
    "conflict",
    "support",
    "criticism",
]

NETWORK_ATTITUDE_TERMS = [
    "批判",
    "非難",
    "難詰",
    "反対",
    "反對",
    "支持",
    "賛成",
    "贊成",
    "賞賛",
    "攻撃",
    "攻擊",
    "排斥",
    "排撃",
    "横暴",
    "暴慢",
    "罪惡",
    "罪悪",
    "膺懲",
    "critic",
    "oppose",
    "support",
    "praise",
    "attack",
    "blame",
]

NETWORK_PLACE_EVENT_TERMS = [
    "東京",
    "大阪",
    "京都",
    "横浜",
    "山梨",
    "甲州",
    "県",
    "府",
    "郡",
    "市",
    "町",
    "村",
    "港",
    "駅",
    "会議",
    "事件",
    "裁判",
    "法廷",
    "公判",
    "總會",
    "創立",
    "設立",
    "総会",
]

NETWORK_INSTITUTION_SUFFIXES = [
    "会社",
    "銀行",
    "鐵道",
    "鉄道",
    "電鐵",
    "電鉄",
    "電燈",
    "電灯",
    "電力",
    "水力",
    "炭鉱",
    "會社",
    "社",
    "組合",
    "商會",
    "商会",
]

OCR_TEXT_PAGE_MARKER_RE = re.compile(r"^===\s*(?P<label>.+?)\s*\(p\.(?P<page>\d+)\)\s*===(?P<rest>.*)$")
OCR_BOILERPLATE_MARKERS = [
    "資料名:",
    "資料名：",
    "著作権法に基づき提供された複写物です",
    "著作権者等の許諾がなければ",
    "国立国会図書館",
]
COMPILED_AUTHOR_STOPWORDS = {
    "本誌",
    "記者",
    "新聞",
    "新聞雜",
    "新聞雑",
    "雜誌",
    "雑誌",
    "東京",
    "会社",
    "會社",
    "電燈",
    "電灯",
    "銀行",
    "資料名",
}


def add_lexicon_entry(lexicon: dict[str, set[str]], name: str | None, entity_type: str) -> None:
    if not name:
        return
    cleaned = str(name).strip()
    if len(cleaned) < 2:
        return
    lexicon.setdefault(cleaned, set()).add(entity_type or "unknown")


def network_entity_lexicon() -> dict[str, set[str]]:
    lexicon: dict[str, set[str]] = {}
    for artifact_path in sorted(get_extractions_dir().glob("*.json")):
        try:
            artifact = load_json(artifact_path)
        except Exception:
            continue
        for entity in artifact.get("entity_records", []):
            entity_type = entity.get("entity_type") or "unknown"
            add_lexicon_entry(lexicon, entity.get("canonical_name"), entity_type)
            add_lexicon_entry(lexicon, entity.get("name_original"), entity_type)
            for alias in entity.get("aliases", []) or []:
                add_lexicon_entry(lexicon, alias, entity_type)
        for keyword in artifact.get("keywords", []) or []:
            add_lexicon_entry(lexicon, keyword, "keyword")
        for term in artifact.get("organization_officer_terms", []) or []:
            add_lexicon_entry(lexicon, term.get("person_name_original"), "person")
            add_lexicon_entry(lexicon, term.get("person_name_normalized"), "person")
            add_lexicon_entry(lexicon, term.get("organization_name_original"), "institution")
            for organization in term.get("overlap_organizations", []) or []:
                add_lexicon_entry(lexicon, organization, "institution")

    if get_db_path().exists():
        try:
            connection = connect()
            for row in connection.execute("SELECT canonical_name, name_original, entity_type, aliases_json FROM evidence_entities").fetchall():
                entity_type = row["entity_type"] or "unknown"
                add_lexicon_entry(lexicon, row["canonical_name"], entity_type)
                add_lexicon_entry(lexicon, row["name_original"], entity_type)
                try:
                    aliases = json.loads(row["aliases_json"] or "[]")
                except json.JSONDecodeError:
                    aliases = []
                for alias in aliases:
                    add_lexicon_entry(lexicon, alias, entity_type)
            for row in connection.execute("SELECT keyword FROM keywords").fetchall():
                add_lexicon_entry(lexicon, row["keyword"], "keyword")
            try:
                officer_rows = connection.execute(
                    """
                    SELECT person_name_original, person_name_normalized, organization_name_original, overlap_organizations_json
                    FROM organization_officer_terms
                    """
                ).fetchall()
            except sqlite3.Error:
                officer_rows = []
            for row in officer_rows:
                add_lexicon_entry(lexicon, row["person_name_original"], "person")
                add_lexicon_entry(lexicon, row["person_name_normalized"], "person")
                add_lexicon_entry(lexicon, row["organization_name_original"], "institution")
                try:
                    organizations = json.loads(row["overlap_organizations_json"] or "[]")
                except json.JSONDecodeError:
                    organizations = []
                for organization in organizations:
                    add_lexicon_entry(lexicon, organization, "institution")
            connection.close()
        except sqlite3.Error:
            pass
    return lexicon


def strip_ocr_boilerplate(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        marker = OCR_TEXT_PAGE_MARKER_RE.match(line)
        if marker:
            line = marker.group("rest").strip()
        for boilerplate in OCR_BOILERPLATE_MARKERS:
            index = line.find(boilerplate)
            if index >= 0:
                line = line[:index].strip()
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def passage_chunks(line: str, max_length: int = 220) -> list[str]:
    chunks: list[str] = []
    current = ""
    parts = re.split(r"(?<=[。！？!?])", line)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if current and len(current) + len(part) > max_length:
            chunks.append(current)
            current = part
        else:
            current = f"{current}{part}" if current else part
    if current:
        chunks.append(current)
    expanded: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_length * 2:
            expanded.append(chunk)
            continue
        for start in range(0, len(chunk), max_length):
            expanded.append(chunk[start : start + max_length])
    return expanded


def candidate_passages_from_text(text: str) -> list[str]:
    passages: list[str] = []
    seen: set[str] = set()
    for raw_line in strip_ocr_boilerplate(text).splitlines():
        normalized = re.sub(r"\s+", " ", raw_line).strip()
        if not normalized:
            continue
        for passage in passage_chunks(normalized):
            passage = passage.strip(" 　")
            if not passage or passage in seen:
                continue
            seen.add(passage)
            passages.append(passage)
    return passages


def parse_page_marked_ocr_text(text: str) -> dict[int, dict[str, str]]:
    pages: dict[int, dict[str, str]] = {}
    current_page: int | None = None
    current_label = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_page, current_label, current_lines
        if current_page is None:
            return
        pages[current_page] = {
            "label": current_label,
            "text": "\n".join(line for line in current_lines if line.strip()).strip(),
        }

    for line in text.splitlines():
        marker = OCR_TEXT_PAGE_MARKER_RE.match(line.strip())
        if marker:
            flush()
            current_page = int(marker.group("page"))
            current_label = marker.group("label").strip()
            rest = marker.group("rest").strip()
            current_lines = [rest] if rest else []
            continue
        if current_page is not None:
            current_lines.append(line)
    flush()
    return pages


def resolve_temporary_ocr_text_path(path_value: str | None) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="temporary_ocr_text_path is required")
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        resolved = resolve_project_relative_path(candidate)
        candidate = resolved if resolved is not None else get_project_dir() / candidate
    candidate = candidate.resolve()
    allowed_roots = {ROOT.resolve(), get_project_dir().resolve()}
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="temporary OCR text path must be inside this project")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Temporary OCR text file not found: {path_value}")
    return candidate


def likely_compiled_author(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"\s+", " ", strip_ocr_boilerplate(text)).strip()
    if not cleaned:
        return None
    windows = [cleaned[:260], cleaned[-260:]]
    patterns = [
        r"(?:著者|筆者|編者|寄稿者|差出人|發信人|発信人|投書者)[:： ]*([一-龥々ァ-ヶー]{2,8})",
        r"([一-龥々ァ-ヶー]{2,8})氏(?:より|から|寄せ|來書|来書|投書)",
        r"([一-龥々ァ-ヶー]{2,6})(?:識|誌|記|述|稿|談)(?:$|[。 　])",
    ]
    for window in windows:
        for pattern in patterns:
            for match in re.finditer(pattern, window):
                name = match.group(1)
                name = re.sub(r"^(?:々長|社長|會長|会長)", "", name)
                if name in COMPILED_AUTHOR_STOPWORDS or len(name) < 2:
                    continue
                if any(stopword in name for stopword in COMPILED_AUTHOR_STOPWORDS):
                    continue
                if name.startswith(("此", "該", "其")) or name.endswith(("雜", "雑")):
                    continue
                return {
                    "author_name": name,
                    "author_confidence": "medium",
                    "author_evidence": match.group(0),
                }
    if "自序" in cleaned[:120] and ("我輩" in cleaned or "實業之世界" in cleaned or "実業之世界" in cleaned):
        return {
            "author_name": "野依秀一",
            "author_confidence": "medium",
            "author_evidence": "自序 and first-person editorial context",
        }
    return None


def compiled_volume_context_for_page(
    page: int,
    text: str,
    previous_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", strip_ocr_boilerplate(text)).strip()
    context = dict(previous_context or {})
    context["page"] = page
    piece_marker_found = False
    title_match = re.search(r"『([^』]{2,40})』", cleaned[:500])
    if title_match and "『" not in title_match.group(1):
        context["article_title"] = title_match.group(1)
        piece_marker_found = True
    elif "自序" in cleaned[:120]:
        context["article_title"] = "自序"
        piece_marker_found = True

    author = likely_compiled_author(text)
    if author:
        context.update(author)
    elif context.get("article_title") == "自序":
        context.update(
            {
                "author_name": "野依秀一",
                "author_confidence": "medium",
                "author_evidence": "自序 context",
            }
        )
    elif piece_marker_found:
        context["author_name"] = ""
        context["author_confidence"] = "unknown"
        context["author_evidence"] = ""
    context.setdefault("author_name", "")
    context.setdefault("author_confidence", "unknown")
    context.setdefault("author_evidence", "")
    return context


def inferred_network_entities(text: str) -> list[dict[str, str]]:
    line = re.sub(r"\s+", " ", text).strip()
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in re.finditer(r"([一-龥々ァ-ヶー]{2,12})(氏|君|翁|男|博士)", line):
        name = match.group(1)
        key = (name, "person")
        if key not in seen:
            seen.add(key)
            candidates.append({"text": name, "entity_type": "person", "source": "inferred"})

    suffix_pattern = "|".join(re.escape(suffix) for suffix in NETWORK_INSTITUTION_SUFFIXES)
    for match in re.finditer(rf"([一-龥々ァ-ヶー]{{2,20}}(?:{suffix_pattern}))", line):
        name = match.group(1)
        if len(name) > 24:
            name = name[-24:]
        entity_type = "company" if any(suffix in name for suffix in ["会社", "會社", "電力", "電燈", "電灯", "水力", "炭鉱"]) else "institution"
        key = (name, entity_type)
        if key not in seen:
            seen.add(key)
            candidates.append({"text": name, "entity_type": entity_type, "source": "inferred"})

    return candidates[:12]


def score_network_passage(
    text: str,
    lexicon: dict[str, set[str]],
    repeated_texts: set[str] | None = None,
) -> dict[str, Any]:
    line = re.sub(r"\s+", " ", text).strip()
    repeated_texts = repeated_texts or set()
    matched_terms: list[dict[str, str]] = []
    seen_terms: set[str] = set()
    for name, entity_types in lexicon.items():
        if name in line and name not in seen_terms:
            seen_terms.add(name)
            matched_terms.append({"text": name, "entity_type": sorted(entity_types)[0]})

    lower = line.lower()
    inferred_entities = [
        entity for entity in inferred_network_entities(line) if entity["text"] not in seen_terms
    ]
    relationship_matches = [term for term in NETWORK_RELATIONSHIP_TERMS if term.lower() in lower]
    attitude_matches = [term for term in NETWORK_ATTITUDE_TERMS if term.lower() in lower]
    place_event_matches = [
        term
        for term in NETWORK_PLACE_EVENT_TERMS
        if term in line
    ]
    has_date_or_era = bool(re.search(r"(明治|大正|昭和|\d{4}|[一二三四五六七八九十〇]+年|[0-9]+年)", line))
    name_starts_sentence = bool(re.match(r"^[一-龥々ァ-ヶー]{2,8}[はがの、, ]", line))
    ocr_noise_penalty = 0
    if len(line) < 16:
        ocr_noise_penalty += 2
    if any(marker in line for marker in OCR_BOILERPLATE_MARKERS):
        ocr_noise_penalty += 3
    if line and sum(1 for char in line if char in "□■�") / max(len(line), 1) > 0.1:
        ocr_noise_penalty += 2
    if re.fullmatch(r"[0-9０-９\s\-.、。]+", line):
        ocr_noise_penalty += 3
    if line in repeated_texts:
        ocr_noise_penalty += 3

    score = 0
    breakdown: dict[str, int] = {}
    if matched_terms:
        breakdown["known_entity_or_keyword"] = 3
        score += 3
    if inferred_entities:
        breakdown["inferred_name_or_institution"] = 2
        score += 2
    entity_count = len(matched_terms) + len(inferred_entities)
    if entity_count >= 2:
        breakdown["two_or_more_known_terms"] = 2
        score += 2
    if relationship_matches:
        breakdown["relationship_language"] = 2
        score += 2
    if attitude_matches:
        breakdown["attitude_language"] = 2
        score += 2
    if place_event_matches or has_date_or_era:
        breakdown["place_event_or_date"] = 1
        score += 1
    if name_starts_sentence:
        breakdown["name_like_sentence_start"] = 1
        score += 1
    if ocr_noise_penalty:
        breakdown["ocr_noise_or_low_information_penalty"] = -ocr_noise_penalty
        score -= ocr_noise_penalty

    reasons = []
    if matched_terms:
        reasons.append("known names or keywords")
    if inferred_entities:
        reasons.append("new name or institution candidate")
    if entity_count >= 2:
        reasons.append("multiple entities in one passage")
    if relationship_matches:
        reasons.append("relationship language")
    if attitude_matches:
        reasons.append("attitude/conflict language")
    if place_event_matches or has_date_or_era:
        reasons.append("place, event, or date marker")
    return {
        "score": score,
        "score_breakdown": breakdown,
        "matched_terms": matched_terms[:12],
        "inferred_entities": inferred_entities[:12],
        "relationship_terms": relationship_matches[:8],
        "attitude_terms": attitude_matches[:8],
        "place_event_terms": place_event_matches[:8],
        "candidate_reason": "; ".join(reasons) if reasons else "below network-priority threshold",
    }


def network_passage_candidates_from_text(
    source_id: str,
    page: int,
    text: str,
    payload: dict[str, Any],
    lexicon: dict[str, set[str]] | None = None,
    threshold: int = 3,
    repeated_texts: set[str] | None = None,
    max_candidates: int = 3,
) -> list[dict[str, Any]]:
    lexicon = lexicon if lexicon is not None else network_entity_lexicon()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    provenance = candidate_provenance(source_id, page, payload)
    for line in candidate_passages_from_text(text):
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        score = score_network_passage(normalized, lexicon, repeated_texts)
        if score["score"] < threshold:
            continue
        digest = hashlib.sha1(f"{source_id}:{page}:network_quote:{normalized}".encode("utf-8")).hexdigest()[:12]
        confidence = "high" if score["score"] >= 6 else "medium"
        candidates.append(
            {
                "candidate_id": f"cand_quote_{digest}",
                "candidate_type": "quote",
                "kind": "quote",
                "source_id": source_id,
                "page": page,
                "label": normalized,
                "quote": normalized,
                "confidence": confidence,
                "status": "candidate",
                "review_status": "candidate",
                "action": "Network-relevant passage; review this quote before saving",
                "provenance": provenance,
                "score": score["score"],
                "score_breakdown": score["score_breakdown"],
                "matched_terms": score["matched_terms"],
                "inferred_entities": score["inferred_entities"],
                "candidate_reason": score["candidate_reason"],
                "network_hints": {
                    "relationship_terms": score["relationship_terms"],
                    "attitude_terms": score["attitude_terms"],
                    "place_event_terms": score["place_event_terms"],
                },
            }
        )
        if payload.get("article_context"):
            candidates[-1]["article_context"] = payload["article_context"]
    return sorted(candidates, key=lambda candidate: candidate.get("score", 0), reverse=True)[:max_candidates]


def resolve_evidence(
    artifact: dict[str, Any],
    source_id: str,
    page: int,
    evidence_id: str,
    quote: str | None = None,
) -> dict[str, Any]:
    if not evidence_id:
        raise HTTPException(status_code=400, detail="Approved evidence_id is required before saving structured evidence")
    for evidence in artifact.get("evidence_quotes", []):
        if evidence.get("evidence_id") != evidence_id:
            continue
        if evidence.get("source_id") != source_id or evidence.get("page") != page:
            raise HTTPException(status_code=400, detail="Evidence quote does not match this source/page")
        if quote and evidence.get("quote") != quote:
            raise HTTPException(status_code=400, detail="Evidence quote text does not match the approved evidence_id")
        return evidence
    raise HTTPException(status_code=400, detail="Evidence quote does not resolve")


def structured_candidates_for_quote(
    artifact: dict[str, Any],
    source_id: str,
    page: int,
    evidence: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    quote = evidence.get("quote", "")
    provenance = candidate_provenance(source_id, page, payload, evidence)
    article_context = payload.get("article_context") or evidence.get("article_context") or {}
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    matched_entities: list[dict[str, Any]] = []

    def base(kind: str, label: str, confidence: str = "medium") -> dict[str, Any]:
        digest = hashlib.sha1(f"{source_id}:{page}:{evidence.get('evidence_id')}:{kind}:{label}".encode("utf-8")).hexdigest()[:12]
        record = {
            "candidate_id": f"cand_{kind}_{digest}",
            "candidate_type": kind,
            "kind": kind,
            "source_id": source_id,
            "page": page,
            "evidence_id": evidence.get("evidence_id"),
            "quote": quote,
            "label": label,
            "confidence": confidence,
            "status": "candidate",
            "provenance": provenance,
        }
        if article_context:
            record["article_context"] = article_context
        return record

    for entity in artifact.get("entity_records", []):
        names = [entity.get("canonical_name", ""), entity.get("name_original", ""), *entity.get("aliases", [])]
        for name in names:
            if not name or name not in quote or ("entity", name) in seen:
                continue
            seen.add(("entity", name))
            entity_type = entity.get("entity_type") or "person"
            kind = "place" if entity_type == "place" else "entity"
            matched_entities.append({"name": name, "entity": entity})
            candidate = base(kind, name, "medium")
            candidate.update(
                {
                    "action": "Create/confirm place mention" if kind == "place" else "Create/confirm mention",
                    "entity": {
                        "entity_id": entity.get("entity_id", ""),
                        "name": name,
                        "entity_type": entity_type,
                    },
                    "entity_id": entity.get("entity_id", ""),
                    "entity_name": name,
                    "entity_type": entity_type,
                }
            )
            candidates.append(candidate)

    for inferred in inferred_network_entities(quote):
        name = inferred["text"]
        entity_type = inferred["entity_type"]
        kind = "place" if entity_type == "place" else "entity"
        if ("entity", name) in seen:
            continue
        seen.add(("entity", name))
        inferred_entity = {
            "entity_id": "",
            "canonical_name": name,
            "name_original": name,
            "entity_type": entity_type,
            "aliases": [],
        }
        matched_entities.append({"name": name, "entity": inferred_entity})
        candidate = base(kind, name, "medium")
        candidate.update(
            {
                "action": "Create/confirm inferred place mention" if kind == "place" else "Create/confirm inferred mention",
                "entity": {
                    "entity_id": "",
                    "name": name,
                    "entity_type": entity_type,
                    "aliases": [],
                },
                "entity_id": "",
                "entity_name": name,
                "entity_type": entity_type,
                "inferred": True,
            }
        )
        candidates.append(candidate)

    for keyword in artifact.get("keywords", []):
        if keyword and keyword in quote and ("keyword", keyword) not in seen:
            seen.add(("keyword", keyword))
            candidate = base("keyword", keyword, "medium")
            candidate.update({"action": "Approve keyword", "keyword": keyword})
            candidates.append(candidate)

    if len(matched_entities) >= 2:
        first = matched_entities[0]["entity"]
        second = matched_entities[1]["entity"]
        label = f"{matched_entities[0]['name']} - {matched_entities[1]['name']}"
        candidate = base("relationship", label, "low")
        candidate.update(
            {
                "action": "Possible relationship; choose relation label before approving",
                "relationship": {
                    "subject": {
                        "entity_id": first.get("entity_id", ""),
                        "name": matched_entities[0]["name"],
                        "entity_type": first.get("entity_type", "person"),
                    },
                    "object": {
                        "entity_id": second.get("entity_id", ""),
                        "name": matched_entities[1]["name"],
                        "entity_type": second.get("entity_type", "person"),
                    },
                    "relation_type": "",
                },
            }
        )
        candidates.append(candidate)

    attitude_terms = [
        "批判",
        "非難",
        "難詰",
        "反対",
        "反對",
        "支持",
        "賛成",
        "贊成",
        "賞賛",
        "攻撃",
        "攻擊",
        "排斥",
        "排撃",
        "横暴",
        "暴慢",
        "膺懲",
        "critic",
        "oppose",
        "support",
        "attack",
        "blame",
    ]
    if any(term.lower() in quote.lower() for term in attitude_terms):
        negative = any(term in quote for term in ["批判", "非難", "難詰", "反対", "反對", "攻撃", "攻擊", "排斥", "排撃", "横暴", "暴慢", "膺懲", "critic", "oppose", "attack", "blame"])
        candidate = base("attitude", quote[:80], "low")
        speaker_name = article_context.get("author_name", "")
        speaker_confidence = article_context.get("author_confidence", "unknown")
        candidate.update(
            {
                "action": "Possible attitude; confirm speaker, target, type, and polarity",
                "attitude": {
                    "attitude_type": "criticism" if negative else "support",
                    "polarity": "negative" if negative else "positive",
                },
            }
        )
        if speaker_name and speaker_confidence != "unknown":
            candidate["attitude"]["speaker"] = {
                "entity_id": "",
                "name": speaker_name,
                "entity_type": "person",
                "confidence": speaker_confidence,
            }
            candidate["note"] = f"Likely attitude holder inferred from article context: {speaker_name}."
        elif article_context:
            candidate["note"] = "Article author is uncertain; confirm the attitude holder in the UI."
        candidates.append(candidate)

    if quote.strip():
        claim_candidate = base("claim", quote[:100], "low")
        claim_candidate.update(
            {
                "action": "Possible claim or observation; review before saving",
                "claim": {"text": quote},
            }
        )
        candidates.append(claim_candidate)
        note_candidate = base("note", quote[:100], "medium")
        note_candidate.update(
            {
                "action": "Create reading note",
                "note": quote,
            }
        )
        candidates.append(note_candidate)

    return candidates[:40]


def ocr_manifest_for_layer(source_id: str, layer: str) -> tuple[dict[str, Any], Path] | None:
    roots = {
        "corrected": get_ocr_corrected_dir(),
        "manual": get_ocr_manual_dir(),
        "raw": get_ocr_raw_dir(),
    }
    root = roots.get(layer)
    if root is None:
        return None
    path = root / source_id / "manifest.json"
    if not path.exists():
        return None
    return load_json(path), path


def best_ocr_for_page(source_id: str, page: int) -> dict[str, Any]:
    sync_batch_ocr_to_project(source_id)
    for layer in ("corrected", "manual", "raw"):
        manifest_info = ocr_manifest_for_layer(source_id, layer)
        if not manifest_info:
            continue
        manifest, manifest_path = manifest_info
        page_json = page_json_path_for(manifest, page)
        if not page_json:
            continue
        page_path = resolve_project_relative_path(page_json)
        if not page_path or not page_path.exists():
            continue
        text = flatten_ocr_text(load_json(page_path))
        return {
            "ocr_layer": layer,
            "ocr_page_json": page_json,
            "ocr_manifest": manifest_path.relative_to(ROOT).as_posix(),
            "ocr_text": text,
            "ocr_status": "needs_ocr_review" if len(text.strip()) < 20 else "loaded",
        }
    return {
        "ocr_layer": "none",
        "ocr_page_json": "",
        "ocr_manifest": "",
        "ocr_text": "",
        "ocr_status": "missing",
    }


def latest_ocr_for_page(source_id: str, page: int) -> dict[str, Any]:
    return best_ocr_for_page(source_id, page)


def biography_sources() -> list[dict[str, Any]]:
    return [source for source in load_sources() if source.get("category") == "Biographies"]


def biography_source_pages(source: dict[str, Any]) -> list[int]:
    source_id = source["source_id"]
    pages: set[int] = set()
    for layer in ("corrected", "manual", "raw"):
        manifest_info = ocr_manifest_for_layer(source_id, layer)
        if manifest_info:
            pages.update(int(page) for page in manifest_info[0].get("pages", []) if isinstance(page, int))
    if pages:
        return sorted(pages)
    count = pdf_page_count(source)
    if isinstance(count, int) and count > 0:
        return list(range(1, count + 1))
    return [1]


def full_pdf_source_pages(source: dict[str, Any]) -> list[int]:
    count = pdf_page_count(source)
    if not isinstance(count, int) or count < 1:
        value = source.get("page_count")
        count = value if isinstance(value, int) and value > 0 else 1
    return list(range(1, count + 1))


def batch_source_pages(source: dict[str, Any], page_scope: str = "available_ocr") -> list[int]:
    if page_scope == "full_pdf":
        return full_pdf_source_pages(source)
    return biography_source_pages(source)


def repeated_ocr_texts_from_records(records: list[dict[str, Any]], min_repeats: int = 3) -> set[str]:
    counts: dict[str, int] = {}
    for ocr in records:
        for line in strip_ocr_boilerplate(ocr.get("ocr_text", "")).splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if len(normalized) < 4:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
    return {line for line, count in counts.items() if count >= min_repeats}


def repeated_ocr_texts_for_pages(source_id: str, pages: list[int], min_repeats: int = 3) -> set[str]:
    records: list[dict[str, Any]] = []
    for page in pages:
        ocr = best_ocr_for_page(source_id, page)
        records.append(ocr)
    return repeated_ocr_texts_from_records(records, min_repeats)


def batch_run_path(run_id: str) -> Path:
    return batch_run_root(run_id) / "manifest.json"


def batch_run_root(run_id: str) -> Path:
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise HTTPException(status_code=400, detail="Invalid batch run id")
    root = get_batch_review_dir().resolve()
    target = (get_batch_review_dir() / run_id).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid batch run path")
    return target


def batch_page_path(run_id: str, source_id: str, page: int) -> Path:
    return batch_run_root(run_id) / "sources" / source_id / "pages" / f"page_{page:04d}.json"


def load_batch_manifest(run_id: str) -> dict[str, Any]:
    path = batch_run_root(run_id) / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Batch biography run not found")
    return load_json(path)


def batch_packet_uses_local_ocr_edits(packet: dict[str, Any]) -> bool:
    return packet.get("ocr_review_status") in {"edited", "approved"} or packet.get("displayed_ocr_layer") == "batch_edited"


def normalize_api_v1_path(path: str) -> str:
    if path.startswith("/reading/"):
        return f"/api/v1{path}"
    if path.startswith("/batch/"):
        return f"/api/v1{path}"
    if path.startswith("/evidence/"):
        return f"/api/v1{path}"
    if path.startswith("/extraction-artifacts/"):
        return f"/api/v1{path}"
    return path


def enrich_batch_packet_ocr_state(packet: dict[str, Any]) -> dict[str, Any]:
    source_id = packet.get("source_id", "")
    page = int(packet.get("page") or 0)
    if source_id and page > 0:
        packet["page_image_url"] = normalize_api_v1_path(
            packet.get("page_image_url") or f"/api/v1/reading/sources/{source_id}/pages/{page}/image"
        )
        packet["pdf_url"] = normalize_api_v1_path(
            packet.get("pdf_url") or f"/api/v1/reading/sources/{source_id}/pdf#page={page}"
        )
    displayed_layer = packet.get("displayed_ocr_layer") or packet.get("ocr_layer") or "none"
    displayed_path = packet.get("displayed_ocr_page_json") or packet.get("ocr_page_json") or ""
    displayed_text = packet.get("displayed_ocr_text")
    if displayed_text is None:
        displayed_text = packet.get("ocr_text", "")
    latest = latest_ocr_for_page(source_id, page) if source_id and page > 0 else {
        "ocr_layer": "none",
        "ocr_page_json": "",
        "ocr_manifest": "",
        "ocr_text": "",
        "ocr_status": "missing",
    }
    packet["displayed_ocr_layer"] = displayed_layer
    packet["displayed_ocr_page_json"] = displayed_path
    packet["displayed_ocr_text"] = displayed_text
    packet["latest_available_ocr_layer"] = latest.get("ocr_layer", "none")
    packet["latest_available_ocr_page_json"] = latest.get("ocr_page_json", "")
    packet["latest_available_ocr_manifest"] = latest.get("ocr_manifest", "")
    packet["latest_available_ocr_status"] = latest.get("ocr_status", "missing")
    packet["latest_available_text_length"] = len(latest.get("ocr_text", ""))
    packet.setdefault("ocr_review_status", "candidate")
    latest_path = latest.get("ocr_page_json", "")
    packet["ocr_is_stale"] = bool(
        latest_path
        and latest_path != displayed_path
        and latest.get("ocr_layer") in {"corrected", "manual", "raw"}
        and displayed_layer != "batch_text"
    )
    if displayed_layer == "batch_text":
        packet["ocr_sync_message"] = "Temporary OCR text is shown for review."
    elif batch_packet_uses_local_ocr_edits(packet) and packet["ocr_is_stale"]:
        packet["ocr_sync_message"] = "Corrected OCR available, batch OCR has local edits."
    elif packet["ocr_is_stale"]:
        packet["ocr_sync_message"] = "Newer OCR is available for this page."
    else:
        packet["ocr_sync_message"] = ""
    return packet


def batch_page_summary(packet: dict[str, Any]) -> dict[str, Any]:
    packet = enrich_batch_packet_ocr_state(packet)
    candidates = packet.get("quote_candidates", []) + packet.get("structured_candidates", [])
    counts: dict[str, int] = {}
    for candidate in candidates:
        key = candidate.get("review_status") or candidate.get("status", "candidate")
        counts[key] = counts.get(key, 0) + 1
    return {
        "run_id": packet.get("run_id", ""),
        "source_id": packet.get("source_id", ""),
        "title": packet.get("title", ""),
        "title_original": packet.get("title_original", ""),
        "page": packet.get("page"),
        "ocr_status": packet.get("ocr_status", ""),
        "ocr_layer": packet.get("ocr_layer", ""),
        "displayed_ocr_layer": packet.get("displayed_ocr_layer", ""),
        "latest_available_ocr_layer": packet.get("latest_available_ocr_layer", ""),
        "ocr_is_stale": packet.get("ocr_is_stale", False),
        "ocr_review_status": packet.get("ocr_review_status", "candidate"),
        "network_review_status": packet.get("network_review_status", ""),
        "quote_candidate_count": len(packet.get("quote_candidates", [])),
        "structured_candidate_count": len(packet.get("structured_candidates", [])),
        "candidate_status_counts": counts,
    }


def generate_batch_candidates(
    source_id: str,
    page: int,
    source: dict[str, Any],
    ocr: dict[str, Any],
    artifact: dict[str, Any] | None = None,
    lexicon: dict[str, set[str]] | None = None,
    repeated_texts: set[str] | None = None,
    threshold: int = 3,
    max_quote_candidates: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    artifact = artifact or reading_extraction_artifact(source_id)
    provenance = {
        "ocr_page_json": ocr.get("ocr_page_json", ""),
        "corrected_ocr_page_json": ocr.get("ocr_page_json", "") if ocr.get("ocr_layer") == "corrected" else "",
        "source_pdf": source_pdf_reference(source),
    }
    if ocr.get("article_context"):
        provenance["article_context"] = ocr["article_context"]
    quote_candidates = network_passage_candidates_from_text(
        source_id,
        page,
        ocr.get("ocr_text", ""),
        provenance,
        lexicon=lexicon,
        threshold=threshold,
        repeated_texts=repeated_texts,
        max_candidates=max_quote_candidates,
    )
    for candidate in quote_candidates:
        candidate["review_status"] = "candidate"
        candidate["source"] = "batch"

    structured_candidates: list[dict[str, Any]] = []
    for quote_candidate in quote_candidates[:3]:
        fake_evidence = {
            "evidence_id": f"batch_{quote_candidate['candidate_id']}",
            "source_id": source_id,
            "page": page,
            "quote": quote_candidate.get("quote", ""),
            "ocr_page_json": ocr.get("ocr_page_json", ""),
            "source_pdf": source_pdf_reference(source),
        }
        if ocr.get("article_context"):
            fake_evidence["article_context"] = ocr["article_context"]
        if ocr.get("ocr_layer") == "corrected":
            fake_evidence["corrected_ocr_page_json"] = ocr.get("ocr_page_json", "")
        for candidate in structured_candidates_for_quote(artifact, source_id, page, fake_evidence, provenance):
            candidate["quote_candidate_id"] = quote_candidate["candidate_id"]
            candidate["evidence_id"] = ""
            candidate["review_status"] = "candidate"
            candidate["source"] = "batch"
            structured_candidates.append(candidate)
    network_status = "network_passages_found" if quote_candidates else "no_priority_passage_found"
    return quote_candidates, structured_candidates, network_status


def source_skill_id_for_worker(source: dict[str, Any]) -> str | None:
    title = f"{source.get('title', '')} {source.get('title_original', '')}"
    if source.get("source_id") == "raw_8ab4cdc4678e" or "東電筆誅錄" in title or "東電筆誅録" in title:
        return "sources/toden_hitchuroku"
    return None


async def enrich_packet_with_worker_candidates(
    packet: dict[str, Any],
    source: dict[str, Any],
    ocr: dict[str, Any],
    *,
    analysis_engine: str,
    analysis_mode: str,
    worker_skill_id: str,
    source_skill_id: str | None,
    max_quote_candidates: int,
) -> dict[str, Any]:
    packet["analysis_engine"] = analysis_engine
    packet["analysis_mode"] = analysis_mode
    if analysis_engine not in {"worker_ai", "worker_ai_with_local_fallback"}:
        packet["worker_ai_status"] = "disabled"
        return packet
    config = worker_config_from_env()
    if not config.available:
        packet["worker_ai_status"] = "not_configured"
        if analysis_engine == "worker_ai":
            packet["quote_candidates"] = []
            packet["network_passage_candidates"] = []
            packet["structured_candidates"] = []
            packet["network_review_status"] = "no_priority_passage_found"
            packet["worker_ai_message"] = "Worker AI is not configured; no local fallback was used."
        else:
            packet["worker_ai_message"] = "Local fallback used. Set POE_API_KEY or OPENROUTER_API_KEY plus a worker model to enable worker AI."
        return packet
    provenance = {
        "ocr_page_json": ocr.get("ocr_page_json", ""),
        "corrected_ocr_page_json": ocr.get("ocr_page_json", "") if ocr.get("ocr_layer") == "corrected" else "",
        "source_pdf": source_pdf_reference(source),
    }
    if ocr.get("article_context"):
        provenance["article_context"] = ocr["article_context"]
    try:
        result = await analyze_page_with_worker(
            source=source,
            page=int(packet["page"]),
            ocr_text=ocr.get("ocr_text", ""),
            provenance=provenance,
            article_context=ocr.get("article_context") or packet.get("article_context") or {},
            analysis_mode=analysis_mode,
            skill_id=worker_skill_id,
            source_skill_id=source_skill_id,
            max_quote_candidates=max_quote_candidates,
        )
    except Exception as exc:
        packet["worker_ai_status"] = "failed"
        if analysis_engine == "worker_ai":
            packet["quote_candidates"] = []
            packet["network_passage_candidates"] = []
            packet["structured_candidates"] = []
            packet["network_review_status"] = "no_priority_passage_found"
            packet["worker_ai_message"] = f"Worker AI failed; no local fallback was used: {exc}"
        else:
            packet["worker_ai_message"] = f"Local fallback used after worker AI failed: {exc}"
        return packet
    packet["worker_ai_status"] = result.get("reason") or "completed"
    packet["worker_ai_provider"] = config.provider
    packet["worker_ai_model"] = result.get("model") or config.model
    packet["worker_passage_count"] = len(result.get("passages", []))
    packet["worker_skipped"] = result.get("skipped", [])
    if result.get("quote_candidates") or result.get("structured_candidates"):
        packet["quote_candidates"] = result.get("quote_candidates", [])
        packet["network_passage_candidates"] = packet["quote_candidates"]
        packet["structured_candidates"] = result.get("structured_candidates", [])
        packet["network_review_status"] = "network_passages_found" if packet["quote_candidates"] else "no_priority_passage_found"
        packet["worker_ai_message"] = "Worker AI suggestions are shown; exact quotes were reconstructed from OCR spans."
    else:
        if analysis_engine == "worker_ai":
            packet["quote_candidates"] = []
            packet["network_passage_candidates"] = []
            packet["structured_candidates"] = []
            packet["network_review_status"] = "no_priority_passage_found"
            packet["worker_ai_message"] = "Worker AI returned no reviewable candidates; no local fallback was used."
        else:
            packet["worker_ai_message"] = "Worker AI returned no reviewable candidates; local fallback suggestions remain."
    packet["updated_at"] = datetime.now(timezone.utc).isoformat()
    return packet


def create_batch_page_packet(
    run_id: str,
    source: dict[str, Any],
    page: int,
    ocr_override: dict[str, Any] | None = None,
    lexicon: dict[str, set[str]] | None = None,
    repeated_texts: set[str] | None = None,
    threshold: int = 3,
    article_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_id = source["source_id"]
    ocr = ocr_override or best_ocr_for_page(source_id, page)
    if article_context:
        ocr = {**ocr, "article_context": article_context}
    artifact = reading_extraction_artifact(source_id)
    quote_candidates, structured_candidates, network_status = generate_batch_candidates(
        source_id,
        page,
        source,
        ocr,
        artifact,
        lexicon=lexicon,
        repeated_texts=repeated_texts,
        threshold=threshold,
    )

    packet = {
        "run_id": run_id,
        "source_id": source_id,
        "title": source.get("title", ""),
        "title_original": source.get("title_original", ""),
        "source_pdf": source_pdf_reference(source),
        "page": page,
        "page_image_url": f"/api/v1/reading/sources/{source_id}/pages/{page}/image",
        "pdf_url": f"/api/v1/reading/sources/{source_id}/pdf#page={page}",
        "ocr_layer": ocr["ocr_layer"],
        "ocr_page_json": ocr["ocr_page_json"],
        "ocr_manifest": ocr["ocr_manifest"],
        "ocr_text": ocr["ocr_text"],
        "ocr_status": ocr["ocr_status"],
        "displayed_ocr_layer": ocr["ocr_layer"],
        "displayed_ocr_page_json": ocr["ocr_page_json"],
        "displayed_ocr_text": ocr["ocr_text"],
        "latest_available_ocr_layer": ocr["ocr_layer"],
        "latest_available_ocr_page_json": ocr["ocr_page_json"],
        "latest_available_ocr_manifest": ocr["ocr_manifest"],
        "ocr_is_stale": False,
        "ocr_review_status": "candidate",
        "article_context": article_context or ocr.get("article_context", {}),
        "page_diagnostics": pdf_diagnostics(source, page=page),
        "quote_candidates": quote_candidates,
        "network_passage_candidates": quote_candidates,
        "network_review_status": network_status,
        "structured_candidates": structured_candidates,
        "review_status": "needs_review",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(batch_page_path(run_id, source_id, page), packet)
    return packet


def write_temporary_text_ocr_records(
    run_id: str,
    source: dict[str, Any],
    ocr_text_path: Path,
    pages: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    parsed_pages = parse_page_marked_ocr_text(ocr_text_path.read_text(encoding="utf-8"))
    if not parsed_pages:
        raise HTTPException(status_code=400, detail="Temporary OCR text file has no page markers")
    selected_pages = pages or sorted(parsed_pages)
    source_id = source["source_id"]
    output_root = get_batch_review_dir() / run_id / "sources" / source_id / "ocr"
    manifest_path = output_root / "manifest.json"
    manifest = {
        "source_id": source_id,
        "run_id": run_id,
        "layer": "batch_text",
        "temporary": True,
        "status": "candidate",
        "source_text_path": to_project_relative_path(ocr_text_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pages": [],
        "page_json": [],
    }
    records: dict[int, dict[str, Any]] = {}
    for page in selected_pages:
        page_record = parsed_pages.get(page)
        if not page_record:
            continue
        text = page_record.get("text", "")
        output_path = output_root / f"page_{page:04d}.json"
        page_json = {
            "contents": [[{"text": text}]],
            "batch_ocr": {
                "run_id": run_id,
                "source_id": source_id,
                "page": page,
                "engine": "temporary_text_file",
                "status": "candidate",
                "temporary": True,
                "source_text_path": to_project_relative_path(ocr_text_path),
                "source_label": page_record.get("label", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        write_json(output_path, page_json)
        relative_page_path = to_project_relative_path(output_path)
        manifest["pages"].append(page)
        manifest["page_json"].append(relative_page_path)
        records[page] = {
            "ocr_layer": "batch_text",
            "ocr_page_json": relative_page_path,
            "ocr_manifest": to_project_relative_path(manifest_path),
            "ocr_text": text,
            "ocr_status": "needs_ocr_review",
            "ocr_temporary": True,
        }
    write_json(manifest_path, manifest)
    return records


async def run_batch_ocr_page(run_id: str, source: dict[str, Any], page: int, engine_id: str, extra_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    engines = get_available_engines()
    if engine_id not in engines:
        raise HTTPException(status_code=400, detail=f"OCR engine is not available: {engine_id}")
    page_image = render_pdf_page_image(source, page)
    
    is_cloud = (engine_id == "paddleocr" or engine_id.startswith("vision_llm_") or engine_id == "mineru")
    temp_path = None
    if is_cloud:
        try:
            import tempfile
            from PIL import Image
            # Create a temporary file path
            temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            with Image.open(page_image) as img:
                gray_img = img.convert("L")
                gray_img.thumbnail((1500, 1500), Image.Resampling.LANCZOS)
                gray_img.save(temp_path, "JPEG", quality=75)
            
            page_image_to_use = temp_path
        except Exception as e:
            print(f"Warning: Failed to compress page image for cloud OCR: {e}")
            page_image_to_use = page_image
    else:
        page_image_to_use = page_image

    try:
        ocr_settings = {"source_id": source["source_id"], "page": page, "region_id": "full_page"}
        if extra_settings:
            ocr_settings.update(extra_settings)
        result = await engines[engine_id].run_ocr(page_image_to_use, ocr_settings)
    except Exception as exc:
        return {
            "ocr_layer": "batch",
            "ocr_page_json": "",
            "ocr_manifest": "",
            "ocr_text": "",
            "ocr_status": f"ocr_failed: {exc}",
        }
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
    page_json = result.get("page_json") or {}
    text = result.get("text") or flatten_ocr_text(page_json)
    page_json.setdefault("batch_ocr", {})
    page_json["batch_ocr"].update(
        {
            "run_id": run_id,
            "source_id": source["source_id"],
            "page": page,
            "engine": engine_id,
            "status": "candidate",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    output_path = get_batch_review_dir() / run_id / "sources" / source["source_id"] / "ocr" / f"page_{page:04d}.json"
    write_json(output_path, page_json)
    register_raw_ocr_for_page(source, page, page_json, engine_id)
    relative_path = to_project_relative_path(output_path)
    return {
        "ocr_layer": "batch",
        "ocr_page_json": relative_path,
        "ocr_manifest": "",
        "ocr_text": text,
        "ocr_status": "needs_ocr_review" if len(text.strip()) < 20 else "loaded",
    }


def refresh_batch_manifest_counts(run_id: str) -> dict[str, Any]:
    manifest = load_batch_manifest(run_id)
    page_paths = sorted((get_batch_review_dir() / run_id / "sources").glob("*/pages/page_*.json"))
    counts = {
        "pages": 0,
        "missing_ocr": 0,
        "needs_ocr_review": 0,
        "quote_candidates": 0,
        "structured_candidates": 0,
        "approved_candidates": 0,
        "rejected_candidates": 0,
        "promoted_candidates": 0,
        "no_priority_pages": 0,
    }
    for page_path in page_paths:
        packet = load_json(page_path)
        counts["pages"] += 1
        if packet.get("network_review_status") == "no_priority_passage_found":
            counts["no_priority_pages"] += 1
        if packet.get("ocr_status") == "missing":
            counts["missing_ocr"] += 1
        if packet.get("ocr_status") == "needs_ocr_review":
            counts["needs_ocr_review"] += 1
        candidates = packet.get("quote_candidates", []) + packet.get("structured_candidates", [])
        counts["quote_candidates"] += len(packet.get("quote_candidates", []))
        counts["structured_candidates"] += len(packet.get("structured_candidates", []))
        counts["approved_candidates"] += sum(1 for candidate in candidates if candidate.get("review_status") == "approved")
        counts["rejected_candidates"] += sum(1 for candidate in candidates if candidate.get("review_status") == "rejected")
        counts["promoted_candidates"] += sum(1 for candidate in candidates if candidate.get("review_status") == "promoted")
    manifest["counts"] = counts
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(batch_run_path(run_id), manifest)
    return manifest


def promote_batch_candidate(
    artifact: dict[str, Any],
    source: dict[str, Any],
    packet: dict[str, Any],
    candidate: dict[str, Any],
    evidence_id_by_quote_candidate: dict[str, str],
) -> dict[str, Any]:
    source_id = packet["source_id"]
    page = int(packet["page"])
    displayed_ocr = packet.get("displayed_ocr_page_json") or packet.get("ocr_page_json", "")
    displayed_layer = packet.get("displayed_ocr_layer") or packet.get("ocr_layer", "")
    raw_ocr = packet.get("ocr_page_json", "") or displayed_ocr
    corrected_ocr = displayed_ocr if displayed_layer == "corrected" else packet.get("corrected_ocr_page_json", "")
    kind = candidate.get("kind") or candidate.get("candidate_type")
    quote = (candidate.get("quote") or candidate.get("label") or "").strip()
    note = candidate.get("note") or ""
    confidence = candidate.get("confidence") or "medium"

    def promoted(kind_value: str) -> dict[str, Any]:
        return {
            "ok": True,
            "kind": kind_value,
            "candidate_id": candidate.get("candidate_id", ""),
        }

    def skipped(reason: str) -> dict[str, Any]:
        return {
            "ok": False,
            "kind": kind or "unknown",
            "candidate_id": candidate.get("candidate_id", ""),
            "reason": reason,
            "source_id": source_id,
            "page": page,
        }

    if kind == "quote":
        if not quote:
            return skipped("missing_quote")
        try:
            evidence_id = ensure_evidence(artifact, source, page, quote, raw_ocr, corrected_ocr, note)
        except HTTPException as exc:
            return skipped(str(exc.detail))
        evidence_id_by_quote_candidate[candidate["candidate_id"]] = evidence_id
        return promoted("quote")

    parent_quote_id = candidate.get("quote_candidate_id")
    evidence_id = evidence_id_by_quote_candidate.get(parent_quote_id or "")
    if not evidence_id:
        return skipped("parent_quote_rejected_or_missing")

    if kind == "keyword":
        keyword = (candidate.get("keyword") or candidate.get("label") or quote).strip()
        if not keyword:
            return skipped("missing_keyword")
        keywords = artifact.setdefault("keywords", [])
        if keyword not in keywords:
            keywords.append(keyword)
        mentions = artifact.setdefault("keyword_mentions", [])
        mentions.append(
            {
                "keyword_mention_id": next_id(mentions, "keyword_mention_id", f"batch_{source_id}_p{page:04d}_kw"),
                "source_id": source_id,
                "page": page,
                "keyword": keyword,
                "evidence_id": evidence_id,
                "quote": quote,
                "confidence": confidence,
                "note": note,
            }
        )
        return promoted("keyword")

    if kind in {"entity", "place"}:
        entity = candidate.get("entity") or {}
        name = entity.get("name") or candidate.get("entity_name") or candidate.get("label") or quote
        if not name:
            return skipped("missing_entity_name")
        entity_id = ensure_entity(
            artifact,
            entity.get("entity_id") or candidate.get("entity_id"),
            name,
            "place" if kind == "place" else entity.get("entity_type") or candidate.get("entity_type") or "person",
            entity.get("aliases") or [],
            note,
        )
        add_mention(artifact, entity_id, source_id, page, name, evidence_id, confidence, note)
        return promoted(kind)

    if kind == "claim":
        claims = artifact.setdefault("claims", [])
        claims.append(
            {
                "claim_id": next_id(claims, "claim_id", f"batch_{source_id}_p{page:04d}_claim"),
                "source_id": source_id,
                "page": page,
                "text": (candidate.get("claim") or {}).get("text") or candidate.get("label") or quote,
                "evidence": quote,
                "evidence_id": evidence_id,
                "quote": quote,
                "confidence": confidence,
                "note": note,
                "extraction_status": "draft",
                "ocr_page_json": corrected_ocr or raw_ocr,
                "source_pdf": source_pdf_reference(source),
            }
        )
        return promoted("claim")

    if kind == "relationship":
        relationship = candidate.get("relationship") or {}
        subject = relationship.get("subject") or {}
        object_record = relationship.get("object") or {}
        relation_type = relationship.get("relation_type") or candidate.get("relation_type")
        subject_name = subject.get("name") or ""
        object_name = object_record.get("name") or ""
        if not subject_name or not object_name or not relation_type:
            return skipped("missing_relationship_fields")
        subject_id = ensure_entity(
            artifact,
            subject.get("entity_id"),
            subject_name,
            subject.get("entity_type") or "person",
            subject.get("aliases") or [],
        )
        object_id = ensure_entity(
            artifact,
            object_record.get("entity_id"),
            object_name,
            object_record.get("entity_type") or "person",
            object_record.get("aliases") or [],
        )
        claims = artifact.setdefault("relationship_claims", [])
        if not any(
            claim.get("subject_entity_id") == subject_id
            and claim.get("object_entity_id") == object_id
            and claim.get("relation_type") == relation_type
            and claim.get("evidence_id") == evidence_id
            for claim in claims
        ):
            claims.append(
                {
                    "relationship_id": next_id(claims, "relationship_id", f"batch_{source_id}_p{page:04d}_rel"),
                    "subject_entity_id": subject_id,
                    "object_entity_id": object_id,
                    "relation_type": relation_type,
                    "source_id": source_id,
                    "page": page,
                    "evidence_id": evidence_id,
                    "quote": quote,
                    "confidence": confidence,
                    "note": note,
                }
            )
        return promoted("relationship")

    if kind == "attitude":
        attitude = candidate.get("attitude") or {}
        speaker = attitude.get("speaker") or {}
        target = attitude.get("target") or {}
        attitude_type = attitude.get("attitude_type") or candidate.get("attitude_type")
        polarity = attitude.get("polarity") or candidate.get("polarity")
        speaker_name = speaker.get("name") or ""
        target_name = target.get("name") or ""
        if not speaker_name or not target_name or not attitude_type or not polarity:
            return skipped("missing_attitude_fields")
        speaker_id = ensure_entity(
            artifact,
            speaker.get("entity_id"),
            speaker_name,
            speaker.get("entity_type") or "person",
            speaker.get("aliases") or [],
        )
        target_id = ensure_entity(
            artifact,
            target.get("entity_id"),
            target_name,
            target.get("entity_type") or "person",
            target.get("aliases") or [],
        )
        claims = artifact.setdefault("attitude_claims", [])
        if not any(
            claim.get("speaker_entity_id") == speaker_id
            and claim.get("target_entity_id") == target_id
            and claim.get("attitude_type") == attitude_type
            and claim.get("polarity") == polarity
            and claim.get("evidence_id") == evidence_id
            for claim in claims
        ):
            claims.append(
                {
                    "attitude_id": next_id(claims, "attitude_id", f"batch_{source_id}_p{page:04d}_att"),
                    "speaker_entity_id": speaker_id,
                    "target_entity_id": target_id,
                    "attitude_type": attitude_type,
                    "polarity": polarity,
                    "source_id": source_id,
                    "page": page,
                    "evidence_id": evidence_id,
                    "quote": quote,
                    "confidence": confidence,
                    "note": note,
                }
            )
        return promoted("attitude")

    if kind == "note":
        notes = artifact.setdefault("reading_notes", [])
        notes.append(
            {
                "note_id": next_id(notes, "note_id", f"batch_{source_id}_p{page:04d}_note"),
                "source_id": source_id,
                "page": page,
                "text": candidate.get("note") or candidate.get("label") or quote,
                "quote": quote,
                "evidence_id": evidence_id,
                "ocr_page_json": corrected_ocr or raw_ocr,
                "corrected_ocr_page_json": corrected_ocr,
                "source_pdf": source_pdf_reference(source),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return promoted("note")

    return skipped("unsupported_candidate_type")


def candidate_highlights(artifact: dict[str, Any], page: int, text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    matched_entities: list[dict[str, Any]] = []
    for entity in artifact.get("entity_records", []):
        names = [entity.get("canonical_name", ""), entity.get("name_original", ""), *entity.get("aliases", [])]
        for name in names:
            if name and name in text and ("entity", name) not in seen:
                seen.add(("entity", name))
                entity_type = entity.get("entity_type") or "person"
                matched_entities.append({"name": name, "entity": entity})
                candidates.append(
                    {
                        "candidate_id": f"cand_entity_{hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]}",
                        "kind": "place" if entity_type == "place" else "entity",
                        "label": name,
                        "quote": name,
                        "entity_id": entity.get("entity_id"),
                        "entity_type": entity_type,
                        "confidence": "medium",
                        "action": "Create/confirm place mention" if entity_type == "place" else "Create/confirm mention",
                    }
                )
    for keyword in artifact.get("keywords", []):
        if keyword and keyword in text and ("keyword", keyword) not in seen:
            seen.add(("keyword", keyword))
            candidates.append(
                {
                    "candidate_id": f"cand_keyword_{hashlib.sha1(keyword.encode('utf-8')).hexdigest()[:10]}",
                    "kind": "keyword",
                    "label": keyword,
                    "quote": keyword,
                    "confidence": "medium",
                    "action": "Approve keyword",
                }
            )
    for evidence in artifact.get("evidence_quotes", []):
        quote = evidence.get("quote", "")
        if evidence.get("page") == page and quote and ("quote", quote) not in seen:
            seen.add(("quote", quote))
            candidates.append(
                {
                    "candidate_id": f"cand_existing_quote_{evidence.get('evidence_id')}",
                    "kind": "quote",
                    "label": quote,
                    "quote": quote,
                    "evidence_id": evidence.get("evidence_id"),
                    "confidence": "medium",
                    "action": "Existing evidence quote",
                }
            )
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 16]
    for line in lines[:8]:
        if ("quote", line) not in seen:
            seen.add(("quote", line))
            candidates.append(
                {
                    "candidate_id": f"cand_quote_{hashlib.sha1(line.encode('utf-8')).hexdigest()[:10]}",
                    "kind": "quote",
                    "label": line,
                    "quote": line,
                    "confidence": "medium",
                    "action": "Candidate quote",
                }
            )
    for line in lines[:5]:
        if ("claim", line) not in seen:
            seen.add(("claim", line))
            candidates.append(
                {
                    "candidate_id": f"cand_claim_{hashlib.sha1(line.encode('utf-8')).hexdigest()[:10]}",
                    "kind": "claim",
                    "label": line[:100],
                    "quote": line,
                    "confidence": "low",
                    "action": "Possible claim or observation; review before saving",
                }
            )
    if len(matched_entities) >= 2:
        first = matched_entities[0]["entity"]
        second = matched_entities[1]["entity"]
        relation_quote = next((line for line in lines if matched_entities[0]["name"] in line and matched_entities[1]["name"] in line), lines[0] if lines else text[:120])
        candidates.append(
            {
                "candidate_id": f"cand_rel_{first.get('entity_id', 'a')}_{second.get('entity_id', 'b')}",
                "kind": "relationship",
                "label": f"{matched_entities[0]['name']} - {matched_entities[1]['name']}",
                "quote": relation_quote,
                "confidence": "low",
                "action": "Possible relationship; choose relation label before approving",
                "relationship": {
                    "subject": {
                        "entity_id": first.get("entity_id", ""),
                        "name": matched_entities[0]["name"],
                        "entity_type": first.get("entity_type", "person"),
                    },
                    "object": {
                        "entity_id": second.get("entity_id", ""),
                        "name": matched_entities[1]["name"],
                        "entity_type": second.get("entity_type", "person"),
                    },
                    "relation_type": "",
                },
            }
        )
    attitude_terms = ["批判", "非難", "反対", "支持", "賛成", "賞賛", "critic", "oppose", "support"]
    attitude_line = next((line for line in lines if any(term.lower() in line.lower() for term in attitude_terms)), "")
    if attitude_line:
        candidates.append(
            {
                "candidate_id": f"cand_att_{hashlib.sha1(attitude_line.encode('utf-8')).hexdigest()[:10]}",
                "kind": "attitude",
                "label": attitude_line[:80],
                "quote": attitude_line,
                "confidence": "low",
                "action": "Possible attitude; confirm speaker, target, type, and polarity",
                "attitude": {
                    "attitude_type": "criticism" if any(term in attitude_line for term in ["批判", "非難", "反対", "critic", "oppose"]) else "support",
                    "polarity": "negative" if any(term in attitude_line for term in ["批判", "非難", "反対", "critic", "oppose"]) else "positive",
                },
            }
        )
    if text.strip():
        note_label = lines[0] if lines else text.strip()[:120]
        candidates.append(
            {
                "candidate_id": f"cand_note_{hashlib.sha1(note_label.encode('utf-8')).hexdigest()[:10]}",
                "kind": "note",
                "label": note_label,
                "quote": note_label,
                "confidence": "medium",
                "action": "Create reading note",
            }
        )
    return candidates[:40]


def set_active_project(project_id: str) -> None:
    ACTIVE_PROJECT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PROJECT_FILE.write_text(project_id.strip(), encoding="utf-8")


def register_raw_ocr_for_page(source: dict[str, Any], page: int, page_json: dict[str, Any], engine_label: str):
    try:
        source_id = source["source_id"]
        raw_page_dir = get_ocr_raw_dir() / source_id / "pages"
        raw_page_dir.mkdir(parents=True, exist_ok=True)
        raw_page_path = raw_page_dir / f"page_{page:04d}.json"
        
        page_json_copy = dict(page_json)
        page_json_copy.setdefault("page_ocr", {
            "source_id": source_id,
            "page": page,
            "ocr_engine": engine_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed",
        })
        write_json(raw_page_path, page_json_copy)
        
        manifest_path = get_ocr_raw_dir() / source_id / "manifest.json"
        if manifest_path.exists():
            manifest = load_json(manifest_path)
        else:
            manifest = {
                "source_id": source_id,
                "source_path": source.get("local_pdf", ""),
                "checksum_sha256": source.get("checksum_sha256", ""),
                "page_range": "",
                "pages": [],
                "page_json": [],
                "ocr_engine": engine_label,
                "ocr_engine_path": "artifacts/ocr/raw",
                "ocr_settings": {
                    "format": "page-json",
                },
                "status": "raw",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_pdf": source_pdf_reference(source),
            }
        
        relative_page_path = to_project_relative_path(raw_page_path)
        page_map = {manifest_page: path for manifest_page, path in zip(manifest.get("pages", []), manifest.get("page_json", []))}
        page_map[page] = relative_page_path
        pages = sorted(page_map)
        manifest["pages"] = pages
        manifest["page_json"] = [page_map[manifest_page] for manifest_page in pages]
        manifest["page_range"] = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
        write_json(manifest_path, manifest)
    except Exception as e:
        print(f"Error registering raw OCR for page: {e}")


def sync_batch_ocr_to_project(source_id: str) -> None:
    try:
        batch_dir = get_batch_review_dir()
        if not batch_dir.exists():
            return
            
        source = None
        try:
            source = source_by_id(source_id)
        except Exception:
            return
            
        run_dirs = sorted(
            [d for d in batch_dir.iterdir() if d.is_dir() and (d.name.startswith("run_ext_") or d.name.startswith("bio_"))],
            key=lambda d: d.name
        )
        if not run_dirs:
            return

        for run_dir in run_dirs:
            ocr_dir = run_dir / "sources" / source_id / "ocr"
            if not ocr_dir.exists():
                continue
                
            engine = "ndlocr_lite"
            run_manifest_path = run_dir / "manifest.json"
            if run_manifest_path.exists():
                try:
                    run_manifest = load_json(run_manifest_path)
                    engine = run_manifest.get("ocr_engine") or engine
                except Exception:
                    pass
                    
            for ocr_file in ocr_dir.glob("page_*.json"):
                match = re.search(r"page_(\d+)\.json", ocr_file.name)
                if not match:
                    continue
                page = int(match.group(1))
                
                raw_page_path = get_ocr_raw_dir() / source_id / "pages" / f"page_{page:04d}.json"
                should_sync = not raw_page_path.exists()
                if not should_sync:
                    try:
                        should_sync = ocr_file.stat().st_mtime > raw_page_path.stat().st_mtime
                    except Exception:
                        pass
                
                if should_sync:
                    try:
                        page_json = load_json(ocr_file)
                        register_raw_ocr_for_page(source, page, page_json, engine)
                    except Exception as e:
                        print(f"Error auto-syncing page {page} from run {run_dir.name}: {e}")
    except Exception as e:
        print(f"Error in sync_batch_ocr_to_project: {e}")


def patch_glirel_compatibility():
    try:
        from glirel import GLiREL
        original_from_pretrained = GLiREL._from_pretrained
        
        @classmethod
        def patched_from_pretrained(cls, *args, **kwargs):
            if "repo_id" in kwargs and "model_id" not in kwargs:
                kwargs["model_id"] = kwargs["repo_id"]
            elif "model_id" in kwargs and "repo_id" not in kwargs:
                kwargs["repo_id"] = kwargs["model_id"]
            return original_from_pretrained(*args, **kwargs)
            
        GLiREL._from_pretrained = patched_from_pretrained
    except Exception:
        pass


def ensure_nlp_dependencies(run_id: str = None, manifest: dict = None):
    try:
        from huggingface_hub import snapshot_download
        
        models_to_download = [
            ("urchade/gliner_multi-v2.1", "GLiNER"),
            ("jackboyla/glirel-large-v0", "GLiREL")
        ]
        
        for repo_id, label in models_to_download:
            print(f"[setup_models] Ensuring model weights for {label} ({repo_id})...")
            if run_id and manifest:
                manifest["status"] = f"Downloading model weights for {label}..."
                write_json(batch_run_path(run_id), manifest)
            
            # Download/verify using the huggingface_hub client directly
            snapshot_download(repo_id=repo_id)
            
    except Exception as exc:
        raise RuntimeError(f"Failed to download NLP model dependencies: {exc}")


def ensure_glirel_config_json_exists():
    try:
        from pathlib import Path
        import os
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            cache_dir = Path(hf_home) / "hub"
        else:
            cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
            
        glirel_cache_dir = cache_dir / "models--jackboyla--glirel-large-v0"
        if glirel_cache_dir.exists():
            snapshots_dir = glirel_cache_dir / "snapshots"
            if snapshots_dir.exists():
                for snapshot_path in snapshots_dir.iterdir():
                    if snapshot_path.is_dir():
                        config_json = snapshot_path / "config.json"
                        if not config_json.exists():
                            config_json.write_text("{}", encoding="utf-8")
    except Exception:
        pass


cancelled_run_ids = set()

def cancel_batch_run(run_id: str):
    cancelled_run_ids.add(run_id)



async def run_batch_nlp_extraction(
    run_id: str,
    source_id: str,
    ocr_engine: str,
    nlp_method: str,
    entity_labels: list[str],
    relation_labels: list[str],
    slm_prompt: str,
    llm_prompt: str,
    ocr_settings: dict[str, Any] | None = None
):
    source = source_by_id(source_id)
    pages = biography_source_pages(source)
    
    run_root = get_batch_review_dir() / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "run_id": run_id,
        "kind": "batch-biographies",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "processing",
        "ocr_engine": ocr_engine,
        "nlp_method": nlp_method,
        "source_ids": [source_id],
        "sources": [source],
        "notes": f"NLP extraction via {nlp_method}",
        "counts": {
            "pages": len(pages),
            "missing_ocr": 0,
            "needs_ocr_review": 0,
            "quote_candidates": 0,
            "structured_candidates": 0,
            "approved_candidates": 0,
            "rejected_candidates": 0,
            "no_priority_pages": 0,
        }
    }
    write_json(batch_run_path(run_id), manifest)
    
    ner_model = None
    re_model = None
    if nlp_method == "gliner":
        need_setup = False
        try:
            from gliner import GLiNER
            from glirel import GLiREL
            import loguru
            from huggingface_hub.constants import HF_HUB_CACHE
            from pathlib import Path
            cache_dir = Path(HF_HUB_CACHE)
            gliner_dir = cache_dir / "models--urchade--gliner_multi-v2.1"
            glirel_dir = cache_dir / "models--jackboyla--glirel-large-v0"
            if not (gliner_dir.exists() and glirel_dir.exists()):
                need_setup = True
        except ImportError:
            need_setup = True
            
        if need_setup:
            manifest["status"] = "Setting up models and dependencies (gliner, glirel, model weights)... This may take a few minutes."
            write_json(batch_run_path(run_id), manifest)
            try:
                ensure_nlp_dependencies(run_id, manifest)
            except Exception as exc:
                manifest["status"] = f"failed: Dependency setup error: {exc}"
                write_json(batch_run_path(run_id), manifest)
                return
                
        try:
            patch_glirel_compatibility()
            
            manifest["status"] = "Loading GLiNER and GLiREL models..."
            write_json(batch_run_path(run_id), manifest)
            
            from gliner import GLiNER
            from glirel import GLiREL
            
            try:
                ner_model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
            except Exception as e:
                try:
                    ner_model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1", local_files_only=True)
                except Exception:
                    raise e

            try:
                re_model = GLiREL.from_pretrained("jackboyla/glirel-large-v0")
            except Exception as e:
                ensure_glirel_config_json_exists()
                try:
                    re_model = GLiREL.from_pretrained("jackboyla/glirel-large-v0", local_files_only=True)
                except Exception:
                    raise e
        except Exception as exc:
            manifest["status"] = f"failed: Model loading error: {exc}"
            write_json(batch_run_path(run_id), manifest)
            return

    ocr_results_by_page = {}
    if ocr_engine == "mineru":
        manifest["status"] = "Preparing MinerU Cloud OCR for PDF..."
        write_json(batch_run_path(run_id), manifest)
        
        engines = get_available_engines()
        mineru_eng = engines.get("mineru")
        if mineru_eng:
            try:
                pdf_path = source_pdf_path(source)
                
                async def ocr_progress(status_text):
                    manifest["status"] = status_text
                    write_json(batch_run_path(run_id), manifest)
                    
                ocr_results_by_page = await mineru_eng.run_ocr_pdf(pdf_path, ocr_settings or {}, progress_callback=ocr_progress)
            except Exception as e:
                manifest["status"] = f"failed: MinerU Cloud OCR failed: {e}"
                write_json(batch_run_path(run_id), manifest)
                return
        else:
            manifest["status"] = "failed: MinerU OCR engine not available."
            write_json(batch_run_path(run_id), manifest)
            return

    phase1_ocr_results = {}
    is_cloud_page_ocr = (ocr_engine == "paddleocr" or ocr_engine.startswith("vision_llm_"))
    if is_cloud_page_ocr:
        manifest["status"] = f"Preparing concurrent cloud OCR for {len(pages)} pages..."
        write_json(batch_run_path(run_id), manifest)
        
        sem = asyncio.Semaphore(3)
        completed_pages = 0
        
        async def process_single_page_ocr(page):
            if run_id in cancelled_run_ids:
                return
            nonlocal completed_pages
            async with sem:
                if run_id in cancelled_run_ids:
                    return
                print(f"[Batch OCR] Starting cloud OCR on page {page} with {ocr_engine}...")
                ocr_res = None
                for attempt in range(1, 4):
                    try:
                        ocr_res = await run_batch_ocr_page(run_id, source, page, ocr_engine, ocr_settings)
                        if "ocr_failed" not in ocr_res.get("ocr_status", ""):
                            print(f"[Batch OCR] Page {page} completed successfully on attempt {attempt}.")
                            break
                    except Exception as e:
                        print(f"[Batch OCR] Page {page} attempt {attempt} failed: {e}")
                        if attempt == 3:
                            ocr_res = {
                                "ocr_layer": "batch",
                                "ocr_page_json": "",
                                "ocr_manifest": "",
                                "ocr_text": "",
                                "ocr_status": f"ocr_failed: {e}",
                            }
                            break
                        await asyncio.sleep(attempt * 2.0)
                
                if ocr_res:
                    phase1_ocr_results[page] = ocr_res
                
                completed_pages += 1
                print(f"[Batch OCR] Cloud OCR Progress: {completed_pages}/{len(pages)} pages done.")
                manifest["status"] = f"Running cloud OCR... ({completed_pages}/{len(pages)} pages done)"
                write_json(batch_run_path(run_id), manifest)

        await asyncio.gather(*(process_single_page_ocr(page) for page in pages))

    total_pages = len(pages)
    for idx, page in enumerate(pages, 1):
        if run_id in cancelled_run_ids:
            manifest["status"] = "stopped"
            write_json(batch_run_path(run_id), manifest)
            print(f"[Batch OCR] Run {run_id} stopped by user.")
            return
        if ocr_engine == "mineru" and page in ocr_results_by_page:
            page_data = ocr_results_by_page[page]
            page_json = page_data.get("page_json") or {}
            text = page_data.get("text") or ""
            
            page_json.setdefault("batch_ocr", {})
            page_json["batch_ocr"].update({
                "run_id": run_id,
                "source_id": source_id,
                "page": page,
                "engine": ocr_engine,
                "status": "candidate",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            
            output_path = get_batch_review_dir() / run_id / "sources" / source_id / "ocr" / f"page_{page:04d}.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(output_path, page_json)
            register_raw_ocr_for_page(source, page, page_json, ocr_engine)
            
            ocr = {
                "ocr_layer": "batch",
                "ocr_page_json": to_project_relative_path(output_path),
                "ocr_manifest": "",
                "ocr_text": text,
                "ocr_status": "needs_ocr_review" if len(text.strip()) < 20 else "loaded",
            }
        else:
            if is_cloud_page_ocr and page in phase1_ocr_results:
                ocr = phase1_ocr_results[page]
            else:
                ocr = best_ocr_for_page(source_id, page)
                should_run_ocr = (ocr_engine != "none" and ocr.get("ocr_layer") != "corrected") or (ocr.get("ocr_status") == "missing" or ocr.get("ocr_layer") == "none")
                if should_run_ocr:
                    if ocr_engine == "none":
                        create_blank_batch_packet(run_id, source, page, ocr)
                        continue
                    manifest["status"] = f"Running OCR on page {page} ({idx}/{total_pages})..."
                    write_json(batch_run_path(run_id), manifest)
                    try:
                        ocr = await run_batch_ocr_page(run_id, source, page, ocr_engine, ocr_settings)
                    except Exception:
                        continue
                
        text = ocr.get("ocr_text", "").strip()
        if not text or nlp_method == "none":
            create_blank_batch_packet(run_id, source, page, ocr)
            continue
            
        print(f"[Batch OCR] Running NLP text processing on page {page} ({idx}/{total_pages})...")
        manifest["status"] = f"Text processing on page {page} ({idx}/{total_pages})..."
        write_json(batch_run_path(run_id), manifest)
        
        quote_candidates = []
        structured_candidates = []
        
        if nlp_method == "gliner" and ner_model and re_model:
            try:
                entities = ner_model.predict_entities(text, entity_labels, threshold=0.3)
                tokens = list(text)
                ner_spans = [[ent['start'], ent['end'], ent['label'], ent['text']] for ent in entities]
                relations = re_model.predict_relations(tokens, relation_labels, ner=ner_spans, threshold=0.1)
                
                sentences = []
                for match in re.finditer(r'[^。\n]+(?:。|\n|$)', text):
                    sent_text = match.group(0).strip()
                    if sent_text:
                        sentences.append({
                            "text": sent_text,
                            "start": match.start(),
                            "end": match.end()
                        })
                        
                for sidx, sent in enumerate(sentences):
                    sent_entities = [ent for ent in entities if ent['start'] >= sent['start'] and ent['end'] <= sent['end']]
                    sent_relations = []
                    for rel in relations:
                        head = rel.get('head_pos') or rel.get('head', [])
                        tail = rel.get('tail_pos') or rel.get('tail', [])
                        if len(head) == 2 and len(tail) == 2:
                            if head[0] >= sent['start'] and head[1] <= sent['end'] and tail[0] >= sent['start'] and tail[1] <= sent['end']:
                                sent_relations.append(rel)
                                
                    if sent_entities or sent_relations:
                        quote_id = f"cand_quote_{run_id}_{page}_{sidx}"
                        quote_candidates.append({
                            "candidate_id": quote_id,
                            "candidate_type": "quote",
                            "kind": "quote",
                            "source_id": source_id,
                            "page": page,
                            "label": sent['text'],
                            "quote": sent['text'],
                            "confidence": "high",
                            "status": "candidate",
                            "review_status": "candidate",
                            "action": "Extracted quote candidate",
                            "provenance": {
                                "ocr_page_json": ocr.get("ocr_page_json", ""),
                                "source_pdf": source_pdf_reference(source),
                            },
                            "score": 5,
                        })
                        
                        for ent in sent_entities:
                            ent_id = f"cand_ent_{run_id}_{page}_{ent['start']}"
                            kind = "place" if ent['label'].lower() in ("place", "location") else "entity"
                            structured_candidates.append({
                                "candidate_id": ent_id,
                                "candidate_type": kind,
                                "kind": kind,
                                "source_id": source_id,
                                "page": page,
                                "quote_candidate_id": quote_id,
                                "label": ent['text'],
                                "entity_name": ent['text'],
                                "entity_type": ent['label'].lower(),
                                "confidence": "medium",
                                "status": "candidate",
                                "review_status": "candidate",
                                "action": f"Confirm {kind} mention",
                            })
                            
                        for ridx, rel in enumerate(sent_relations):
                            rel_id = f"cand_rel_{run_id}_{page}_{ridx}"
                            head = rel.get('head_pos') or rel.get('head', [])
                            tail = rel.get('tail_pos') or rel.get('tail', [])
                            if len(head) == 2 and len(tail) == 2:
                                head_text = text[head[0]:head[1]]
                                tail_text = text[tail[0]:tail[1]]
                            else:
                                head_text = "".join(rel.get('head_text', [])) or "subject"
                                tail_text = "".join(rel.get('tail_text', [])) or "object"
                            structured_candidates.append({
                                "candidate_id": rel_id,
                                "candidate_type": "relationship",
                                "kind": "relationship",
                                "source_id": source_id,
                                "page": page,
                                "quote_candidate_id": quote_id,
                                "label": f"{head_text} - {tail_text}",
                                "confidence": "medium",
                                "status": "candidate",
                                "review_status": "candidate",
                                "action": "Confirm relationship",
                                "relationship": {
                                    "subject": {
                                        "name": head_text,
                                        "entity_type": "person",
                                    },
                                    "object": {
                                        "name": tail_text,
                                        "entity_type": "person",
                                    },
                                    "relation_type": rel.get('label', 'associated'),
                                }
                            })
            except Exception:
                pass
                
        elif nlp_method in ("slm", "llm_api"):
            try:
                raw_response = ""
                system_prompt = (
                    "You are a professional research assistant. Analyze the following Japanese text and extract "
                    "significant entities (Person, Place, Organization) and the relationships between them. "
                    "You must return ONLY a JSON object matching this schema, with no preamble, markdown code blocks, or explanations:\n"
                    "{\n"
                    "  \"quotes\": [\n"
                    "    {\n"
                    "      \"text\": \"Exact quote from the text that contains the facts\",\n"
                    "      \"entities\": [\n"
                    "        {\"name\": \"Entity Name\", \"type\": \"person/place/organization\"}\n"
                    "      ],\n"
                    "      \"relationships\": [\n"
                    "        {\"subject\": \"Subject Entity Name\", \"relation_type\": \"spouse/parent/child/employer/etc\", \"object\": \"Object Entity Name\"}\n"
                    "      ]\n"
                    "    }\n"
                    "  ]\n"
                    "}"
                )
                
                if nlp_method == "slm":
                    prompt_input = f"{slm_prompt}\n\nText:\n{text}"
                    raw_response = await call_ollama_local(prompt_input, system_prompt)
                else:
                    prompt_input = f"{llm_prompt}\n\nText:\n{text}"
                    raw_response = await call_cloud_llm_api(prompt_input, system_prompt)
                    
                parsed_data = parse_json_from_text(raw_response)
                
                for idx, q_item in enumerate(parsed_data.get("quotes", [])):
                    quote_text = q_item.get("text", "").strip()
                    if not quote_text:
                        continue
                    quote_id = f"cand_quote_{run_id}_{page}_{idx}"
                    quote_candidates.append({
                        "candidate_id": quote_id,
                        "candidate_type": "quote",
                        "kind": "quote",
                        "source_id": source_id,
                        "page": page,
                        "label": quote_text,
                        "quote": quote_text,
                        "confidence": "high",
                        "status": "candidate",
                        "review_status": "candidate",
                        "action": "Extracted quote candidate",
                        "provenance": {
                            "ocr_page_json": ocr.get("ocr_page_json", ""),
                            "source_pdf": source_pdf_reference(source),
                        },
                        "score": 5,
                    })
                    
                    for e_idx, ent in enumerate(q_item.get("entities", [])):
                        ent_name = ent.get("name", "").strip()
                        if not ent_name:
                            continue
                        ent_id = f"cand_ent_{run_id}_{page}_{idx}_{e_idx}"
                        kind = "place" if ent.get("type", "").lower() in ("place", "location") else "entity"
                        structured_candidates.append({
                            "candidate_id": ent_id,
                            "candidate_type": kind,
                            "kind": kind,
                            "source_id": source_id,
                            "page": page,
                            "quote_candidate_id": quote_id,
                            "label": ent_name,
                            "entity_name": ent_name,
                            "entity_type": ent.get("type", "person").lower(),
                            "confidence": "medium",
                            "status": "candidate",
                            "review_status": "candidate",
                            "action": f"Confirm {kind} mention",
                        })
                        
                    for r_idx, rel in enumerate(q_item.get("relationships", [])):
                        subj = rel.get("subject", "").strip()
                        obj = rel.get("object", "").strip()
                        if not subj or not obj:
                            continue
                        rel_id = f"cand_rel_{run_id}_{page}_{idx}_{r_idx}"
                        structured_candidates.append({
                            "candidate_id": rel_id,
                            "candidate_type": "relationship",
                            "kind": "relationship",
                            "source_id": source_id,
                            "page": page,
                            "quote_candidate_id": quote_id,
                            "label": f"{subj} - {obj}",
                            "confidence": "medium",
                            "status": "candidate",
                            "review_status": "candidate",
                            "action": "Confirm relationship",
                            "relationship": {
                                "subject": {
                                    "name": subj,
                                    "entity_type": "person",
                                },
                                "object": {
                                    "name": obj,
                                    "entity_type": "person",
                                },
                                "relation_type": rel.get("relation_type", "associated"),
                            }
                        })
            except Exception:
                pass
                
        packet = {
            "run_id": run_id,
            "source_id": source_id,
            "title": source.get("title", ""),
            "title_original": source.get("title_original", ""),
            "source_pdf": source_pdf_reference(source),
            "page": page,
            "page_image_url": f"/reading/sources/{source_id}/pages/{page}/image",
            "pdf_url": f"/reading/sources/{source_id}/pdf#page={page}",
            "ocr_layer": ocr.get("ocr_layer", "raw"),
            "ocr_page_json": ocr.get("ocr_page_json", ""),
            "ocr_manifest": ocr.get("ocr_manifest", ""),
            "ocr_text": text,
            "ocr_status": ocr.get("ocr_status", "loaded"),
            "displayed_ocr_layer": ocr.get("ocr_layer", "raw"),
            "displayed_ocr_page_json": ocr.get("ocr_page_json", ""),
            "displayed_ocr_text": text,
            "latest_available_ocr_layer": ocr.get("ocr_layer", "raw"),
            "latest_available_ocr_page_json": ocr.get("ocr_page_json", ""),
            "ocr_is_stale": False,
            "ocr_review_status": "candidate",
            "quote_candidates": quote_candidates,
            "network_passage_candidates": quote_candidates,
            "network_review_status": "network_passages_found" if quote_candidates else "no_priority_passage_found",
            "structured_candidates": structured_candidates,
            "review_status": "needs_review",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(batch_page_path(run_id, source_id, page), packet)
        
    manifest["status"] = "completed"
    write_json(batch_run_path(run_id), manifest)
    refresh_batch_manifest_counts(run_id)


def create_blank_batch_packet(run_id: str, source: dict[str, Any], page: int, ocr: dict[str, Any]):
    packet = {
        "run_id": run_id,
        "source_id": source["source_id"],
        "title": source.get("title", ""),
        "title_original": source.get("title_original", ""),
        "source_pdf": source_pdf_reference(source),
        "page": page,
        "page_image_url": f"/reading/sources/{source['source_id']}/pages/{page}/image",
        "pdf_url": f"/reading/sources/{source['source_id']}/pdf#page={page}",
        "ocr_layer": ocr.get("ocr_layer", "raw"),
        "ocr_page_json": ocr.get("ocr_page_json", ""),
        "ocr_manifest": ocr.get("ocr_manifest", ""),
        "ocr_text": ocr.get("ocr_text", ""),
        "ocr_status": ocr.get("ocr_status", "loaded"),
        "displayed_ocr_layer": ocr.get("ocr_layer", "raw"),
        "displayed_ocr_page_json": ocr.get("ocr_page_json", ""),
        "displayed_ocr_text": ocr.get("ocr_text", ""),
        "latest_available_ocr_layer": ocr.get("ocr_layer", "raw"),
        "latest_available_ocr_page_json": ocr.get("ocr_page_json", ""),
        "ocr_is_stale": False,
        "ocr_review_status": "candidate",
        "quote_candidates": [],
        "network_passage_candidates": [],
        "network_review_status": "no_priority_passage_found",
        "structured_candidates": [],
        "review_status": "needs_review",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(batch_page_path(run_id, source["source_id"], page), packet)


def parse_json_from_text(text: str) -> dict[str, Any]:
    text = text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception:
        return {}


async def call_ollama_local(prompt: str, system_prompt: str) -> str:
    import httpx
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": "gemma2",
        "prompt": f"{system_prompt}\n\nInput Text:\n{prompt}",
        "stream": False,
        "format": "json"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=60.0)
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            raise RuntimeError(f"Ollama API error: {response.text}")


async def call_cloud_llm_api(prompt: str, system_prompt: str) -> str:
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_prompt}\n\nInput Text:\n{prompt}"}
                    ]
                }
            ]
        }
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            if response.status_code == 200:
                res_data = response.json()
                try:
                    return res_data["candidates"][0]["content"]["parts"][0]["text"]
                except Exception:
                    pass
            raise RuntimeError(f"Gemini API failure: {response.text}")
            
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                res_data = response.json()
                try:
                    return res_data["choices"][0]["message"]["content"]
                except Exception:
                    pass
            raise RuntimeError(f"OpenAI API failure: {response.text}")
            
    raise ValueError("No Cloud LLM API Key (GEMINI_API_KEY or OPENAI_API_KEY) found in env.")
