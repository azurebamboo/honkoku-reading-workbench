from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

import backend.app.services.workbench as wb
from backend.app.services.workbench import *

router = APIRouter()


def source_by_id(*args: Any, **kwargs: Any) -> Any:
    return wb.source_by_id(*args, **kwargs)


def render_pdf_page_image(*args: Any, **kwargs: Any) -> Any:
    return wb.render_pdf_page_image(*args, **kwargs)


def render_pdf_page_image_rotated(*args: Any, **kwargs: Any) -> Any:
    return wb.render_pdf_page_image_rotated(*args, **kwargs)


def get_available_engines(*args: Any, **kwargs: Any) -> Any:
    return wb.get_available_engines(*args, **kwargs)

@router.get("/api/v1/reading/sources/{source_id}/pdf")
def reading_source_pdf(source_id: str) -> FileResponse:
    source = source_by_id(source_id)
    return FileResponse(source_pdf_path(source), media_type="application/pdf")


@router.get("/api/v1/reading/sources/{source_id}/pages/{page}/image")
def reading_source_page_image(source_id: str, page: int, rotation: int = 0) -> FileResponse:
    source = source_by_id(source_id)
    image_path = render_pdf_page_image_rotated(source, page, rotation)
    return FileResponse(image_path, media_type="image/png")


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/rerender")
def rerender_reading_source_page(source_id: str, page: int) -> dict[str, Any]:
    source = source_by_id(source_id)
    image_path = rendered_page_image_path(source_id, page)
    if image_path.exists():
        image_path.unlink()
    
    # Also delete any rotated cached copies of this page image
    for rotated_path in image_path.parent.glob(f"{image_path.stem}_rot*.png"):
        try:
            rotated_path.unlink()
        except OSError:
            pass

    new_image_path = render_pdf_page_image(source, page)
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "page_image": new_image_path.relative_to(wb.ROOT).as_posix(),
        "message": "Page image cache cleared and rendered again.",
    }


@router.get("/api/v1/reading/sources/{source_id}/pages/{page}/regions/{region_id}/image")
def reading_source_region_image(source_id: str, page: int, region_id: str) -> FileResponse:
    image_path = rendered_region_image_path(source_id, page, region_id)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Region image not found")
    return FileResponse(image_path, media_type="image/png")


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/regions")
async def create_reading_region(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    region = payload.get("region") or {}
    rotation = int(payload.get("rotation") or 0)
    if not isinstance(region, dict):
        raise HTTPException(status_code=400, detail="Region must be an object")
    label = payload.get("label") or "table-region"
    seed = json.dumps({"source_id": source_id, "page": page, "region": region, "label": label}, sort_keys=True)
    region_id = payload.get("region_id") or f"reg_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"
    crop_path = crop_page_region(source, page, region, region_id, rotation)
    relative_crop = crop_path.relative_to(wb.ROOT).as_posix()
    return {
        "region_id": region_id,
        "source_id": source_id,
        "page": page,
        "label": label,
        "region": {
            "region_id": region_id,
            "unit": "relative",
            "x": float(region.get("x", 0)),
            "y": float(region.get("y", 0)),
            "width": float(region.get("width", 1)),
            "height": float(region.get("height", 1)),
        },
        "crop_image": relative_crop,
        "crop_image_url": f"/api/v1/reading/sources/{source_id}/pages/{page}/regions/{region_id}/image",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/ocr")
async def ocr_reading_full_page(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    parsing_engine = str(payload.get("parsing_engine") or "ndlocr_lite")
    rotation = int(payload.get("rotation") or 0)
    page_image = render_pdf_page_image_rotated(source, page, rotation)
    engines = get_available_engines()
    if parsing_engine not in engines:
        fallback = "ndlocr_lite" if "ndlocr_lite" in engines else list(engines.keys())[0]
        selected_engine = engines[fallback]
        engine_id_used = fallback
    else:
        selected_engine = engines[parsing_engine]
        engine_id_used = parsing_engine

    try:
        ocr_result = await selected_engine.run_ocr(
            page_image,
            {
                "source_id": source_id,
                "page": page,
                "region_id": "full_page",
                **payload
            },
        )
        page_json = ocr_result.get("page_json") or {}
        text = ocr_result.get("text") or flatten_ocr_text(page_json)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Full-page OCR execution failed using {selected_engine.label}: {exc}")

    region_id = "full_page"
    relative_image = page_image.relative_to(wb.ROOT).as_posix()
    page_json.setdefault("imginfo", {})["img_path"] = relative_image
    page_json["page_ocr"] = {
        "source_id": source_id,
        "page": page,
        "region_id": region_id,
        "region": {
            "unit": "relative",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
        },
        "page_image": relative_image,
        "source_pdf": source_pdf_reference(source),
        "ocr_engine": selected_engine.label,
        "requested_parsing_engine": parsing_engine,
        "ocr_engine_path": "",
        "ocr_settings": {
            "scope": "full_page",
            "json_only": True,
            "device": "cpu",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    tracked_path = region_ocr_json_path(source_id, page, region_id)
    write_json(tracked_path, page_json)
    relative_json = tracked_path.relative_to(wb.ROOT).as_posix()
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "region_id": region_id,
        "region": page_json["page_ocr"]["region"],
        "ocr_page_json": relative_json,
        "region_ocr_json": relative_json,
        "text": text,
        "engine": selected_engine.label,
        "parsing_engine": engine_id_used,
        "status": "completed",
        "message": "Whole-page OCR completed. Review the text before saving OCR correction.",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/regions/ocr")
async def ocr_reading_region(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    parsing_engine = str(payload.get("parsing_engine") or "ndlocr_lite")
    ocr_mode = str(payload.get("ocr_mode") or "text")
    output_format = str(payload.get("output_format") or "markdown_csv")
    region = payload.get("region") or {}
    rotation = int(payload.get("rotation") or 0)
    if region and not isinstance(region, dict):
        raise HTTPException(status_code=400, detail="Region must be an object")

    crop_image = payload.get("crop_image") or ""
    if crop_image:
        crop_path = relative_existing_path(crop_image, "crop_image")
        requested_region_id = payload.get("region_id") or region.get("region_id") or Path(crop_image).stem
        region_id = sanitize_region_id(str(requested_region_id))
    else:
        if not region:
            raise HTTPException(status_code=400, detail="Select a region before running OCR")
        label = payload.get("label") or "region-ocr"
        seed = json.dumps({"source_id": source_id, "page": page, "region": region, "label": label}, sort_keys=True)
        region_id = sanitize_region_id(str(payload.get("region_id") or f"reg_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"))
        crop_path = crop_page_region(source, page, region, region_id, rotation)
        crop_image = crop_path.relative_to(wb.ROOT).as_posix()

    engines = get_available_engines()
    if parsing_engine not in engines:
        fallback = "ndlocr_lite" if "ndlocr_lite" in engines else list(engines.keys())[0]
        selected_engine = engines[fallback]
        engine_id_used = fallback
    else:
        selected_engine = engines[parsing_engine]
        engine_id_used = parsing_engine

    try:
        ocr_result = await selected_engine.run_ocr(
            crop_path,
            {
                "source_id": source_id,
                "page": page,
                "region_id": region_id,
                **payload
            }
        )
        page_json = ocr_result["page_json"]
        text = ocr_result["text"]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OCR execution failed using {selected_engine.label}: {exc}")

    imginfo = page_json.setdefault("imginfo", {})
    imginfo["img_path"] = crop_path.relative_to(wb.ROOT).as_posix()
    if not text.strip():
        text = ""

    provenance = {
        "source_id": source_id,
        "page": page,
        "region_id": region_id,
        "region": {
            "unit": region.get("unit", "relative") if isinstance(region, dict) else "relative",
            "x": region.get("x") if isinstance(region, dict) else None,
            "y": region.get("y") if isinstance(region, dict) else None,
            "width": region.get("width") if isinstance(region, dict) else None,
            "height": region.get("height") if isinstance(region, dict) else None,
        },
        "crop_image": crop_image,
        "ocr_engine": selected_engine.label,
        "requested_parsing_engine": parsing_engine,
        "ocr_mode": ocr_mode,
        "output_format": output_format,
        "ocr_engine_path": "",
        "ocr_settings": {
            "scope": "selected_region",
            "json_only": True,
            "device": "cpu",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    page_json["region_ocr"] = provenance

    tracked_path = region_ocr_json_path(source_id, page, region_id)
    write_json(tracked_path, page_json)
    relative_json = tracked_path.relative_to(wb.ROOT).as_posix()
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "region_id": region_id,
        "crop_image": crop_image,
        "crop_image_url": f"/api/v1/reading/sources/{source_id}/pages/{page}/regions/{region_id}/image",
        "region_ocr_json": relative_json,
        "text": text,
        "engine": selected_engine.label,
        "parsing_engine": engine_id_used,
        "ocr_mode": ocr_mode,
        "output_format": output_format,
        "status": "completed",
        "message": "Selected region OCR completed. Review the text before saving OCR correction.",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/regions/table-parse")
async def parse_reading_region_table(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    parsing_engine = str(payload.get("parsing_engine") or "ndlocr_lite")
    ocr_mode = str(payload.get("ocr_mode") or "table")
    output_format = str(payload.get("output_format") or "markdown_csv")
    region = payload.get("region") or {}
    if region and not isinstance(region, dict):
        raise HTTPException(status_code=400, detail="Region must be an object")
    table_title = payload.get("table_title") or "Selected table"
    region_id = sanitize_region_id(
        str(payload.get("region_id") or region.get("region_id") or f"reg_{hashlib.sha1(json.dumps(region, sort_keys=True).encode('utf-8')).hexdigest()[:10]}")
    )

    crop_image = payload.get("crop_image") or ""
    if crop_image:
        relative_existing_path(crop_image, "crop_image")
    elif region:
        crop_path = crop_page_region(source, page, region, region_id)
        crop_image = crop_path.relative_to(wb.ROOT).as_posix()

    engines = get_available_engines()
    selected_engine = engines.get(parsing_engine)
    table_result = None
    
    if selected_engine and hasattr(selected_engine, "run_table_parse"):
        try:
            if crop_image:
                crop_path = resolve_project_relative_path(crop_image)
                table_result = await selected_engine.run_table_parse(
                    crop_path,
                    {
                        "source_id": source_id,
                        "page": page,
                        "region_id": region_id,
                    }
                )
        except Exception as exc:
            table_result = None

    if table_result:
        ocr_text = table_result["flat_ocr_text"]
        markdown_draft = table_result["markdown_draft"]
        csv_draft = table_result["csv_draft"]
        rows = table_result["rows"]
        columns = table_result["columns"]
        parser = table_result["parser"]
        region_ocr_json = ""
    else:
        ocr_text = payload.get("ocr_text") or ""
        region_ocr_json = payload.get("region_ocr_json") or ""
        if not ocr_text and region_ocr_json:
            region_json_path = relative_existing_path(region_ocr_json, "region_ocr_json")
            ocr_text = flatten_ocr_text(load_json(region_json_path))

        rows = draft_table_rows_from_text(ocr_text)
        columns = table_columns_from_rows(rows)
        markdown_draft = table_rows_to_markdown(rows)
        csv_draft = table_rows_to_csv(rows)
        parser = {
            "engine": "line_split_table_draft",
            "requested_engine": parsing_engine,
            "method": "Conservative draft from OCR lines; cells are proposals for human review.",
            "status": "needs_review",
        }

    packet = {
        "table_parse_id": f"tblparse_{source_id}_p{page:04d}_{region_id}",
        "source_id": source_id,
        "page": page,
        "table_title": table_title,
        "ocr_mode": ocr_mode,
        "parsing_engine": parsing_engine,
        "output_format": output_format,
        "source_pdf": source_pdf_reference(source),
        "crop_image": crop_image,
        "region": region or {"unit": "relative", "x": None, "y": None, "width": None, "height": None},
        "region_id": region_id,
        "region_ocr_json": region_ocr_json,
        "flat_ocr_text": ocr_text,
        "markdown_draft": markdown_draft,
        "csv_draft": csv_draft,
        "columns": columns,
        "rows": rows,
        "parser": parser,
        "review_status": "needs_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": "This packet is a table review draft only. Reviewed structured rows should be promoted into the appropriate extraction artifact.",
    }
    packet_path = table_review_json_path(source_id, page, region_id)
    write_json(packet_path, packet)
    return {
        "ok": True,
        "table_parse": packet,
        "table_parse_json": packet_path.relative_to(wb.ROOT).as_posix(),
        "message": "Draft table review packet created. Check and correct cells before using structured rows.",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/analyze")
async def analyze_reading_text(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source_by_id(source_id)
    payload = await request.json()
    text = payload.get("text") or ""
    quote = payload.get("quote") or ""
    analysis_text = "\n".join(part.strip() for part in (text, quote) if isinstance(part, str) and part.strip())
    if not analysis_text:
        raise HTTPException(status_code=400, detail="Text is required before analysis")
    artifact = reading_extraction_artifact(source_id)
    candidates = candidate_highlights(artifact, page, analysis_text)
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "analysis_engine": "local_rule_candidates_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ocr_page_json": payload.get("ocr_page_json") or "",
        "corrected_ocr_page_json": payload.get("corrected_ocr_page_json") or "",
        "candidates": candidates,
        "message": f"Generated {len(candidates)} editable candidate(s). Review before saving.",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/analyze-quotes")
async def analyze_reading_quotes(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source_by_id(source_id)
    payload = await request.json()
    text = payload.get("text") or ""
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Checked OCR text is required before quote analysis")
    candidates = quote_candidates_from_text(source_id, page, text, payload)
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "analysis_engine": "local_quote_candidates_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "message": f"Generated {len(candidates)} quote candidate(s). Select or approve a quote before structured analysis.",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/analyze-quote")
async def analyze_reading_quote(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source_by_id(source_id)
    payload = await request.json()
    evidence_id = payload.get("evidence_id") or ""
    quote = payload.get("quote") or ""
    artifact = reading_extraction_artifact(source_id)
    evidence = resolve_evidence(artifact, source_id, page, evidence_id, quote or None)
    candidates = structured_candidates_for_quote(artifact, source_id, page, evidence, payload)
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "evidence_id": evidence_id,
        "quote": evidence.get("quote", ""),
        "analysis_engine": "local_quote_structured_candidates_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
        "message": f"Generated {len(candidates)} structured candidate(s) from the approved quote.",
    }


def validate_imported_table_json(data: Any, source_id: str) -> dict[str, Any]:
    errors: list[str] = []
    detected_schema = ""
    target_import = "review_packet_only"
    database_compatible = False

    if not isinstance(data, dict):
        return {
            "detected_schema": "",
            "database_compatible": False,
            "target_import": target_import,
            "validation_errors": ["Top-level JSON value must be an object."],
        }

    schema = data.get("extraction_schema_version")
    table_schema = data.get("table_schema_version")
    if schema == "evidence-graph-v1":
        detected_schema = "evidence-graph-v1"
        target_import = "artifacts/extractions/<source_id>.json"
        for field in ("source_id", "extraction_scope", "evidence_quotes"):
            if field not in data:
                errors.append(f"Missing `{field}`.")
        if data.get("source_id") and data.get("source_id") != source_id:
            errors.append("JSON source_id does not match the selected Reading Desk source.")
        if not isinstance(data.get("evidence_quotes", []), list):
            errors.append("`evidence_quotes` must be a list.")
        database_compatible = not errors
    elif schema == "secondary-table-v1" and table_schema == "organization-officer-timeline-v1":
        detected_schema = "secondary-table-v1 / organization-officer-timeline-v1"
        target_import = "artifacts/extractions/<artifact_id>.json"
        tables = data.get("organization_officer_tables")
        terms = data.get("organization_officer_terms")
        if not isinstance(tables, list):
            errors.append("`organization_officer_tables` must be a list.")
        if not isinstance(terms, list):
            errors.append("`organization_officer_terms` must be a list.")
        if data.get("source_id") and data.get("source_id") != source_id:
            errors.append("JSON source_id does not match the selected Reading Desk source.")
        database_compatible = not errors
    elif schema:
        detected_schema = str(schema)
        errors.append(f"`{schema}` is not a database-compatible import schema yet.")
    else:
        errors.append("No supported `extraction_schema_version` found.")

    return {
        "detected_schema": detected_schema,
        "database_compatible": database_compatible,
        "target_import": target_import if database_compatible else "review_packet_only",
        "validation_errors": errors,
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/table-review-import")
async def import_table_review(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    csv_text = payload.get("csv_text") or ""
    markdown_text = payload.get("markdown_text") or ""
    json_text = payload.get("json_text") or ""
    parsed_json = None
    json_validation = {
        "detected_schema": "",
        "database_compatible": False,
        "target_import": "review_packet_only",
        "validation_errors": [],
    }
    if json_text.strip():
        try:
            parsed_json = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON table content is invalid: {exc}") from exc
        json_validation = validate_imported_table_json(parsed_json, source_id)
    if not csv_text.strip() and not markdown_text.strip() and not json_text.strip():
        raise HTTPException(status_code=400, detail="CSV, Markdown, or JSON table content is required")
    parser_name = payload.get("parser_name") or "external_table_agent"
    review_status = payload.get("review_status") or "needs_review"
    import_seed = json.dumps(
        {
            "source_id": source_id,
            "page": page,
            "parser_name": parser_name,
            "csv_text": csv_text,
            "markdown_text": markdown_text,
            "json_text": json_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    import_id = f"external_{hashlib.sha1(import_seed.encode('utf-8')).hexdigest()[:12]}"
    rows = rows_from_csv_text(csv_text)
    packet = {
        "table_parse_id": f"tblimport_{source_id}_p{page:04d}_{import_id}",
        "source_id": source_id,
        "page": page,
        "printed_page": payload.get("printed_page") or "",
        "table_title": payload.get("table_title") or "External table review import",
        "source_pdf": source_pdf_reference(source),
        "crop_image": payload.get("crop_image") or "",
        "region": payload.get("region") or {},
        "region_id": payload.get("region_id") or "",
        "parser": {
            "engine": parser_name,
            "method": "Externally prepared CSV/Markdown/JSON table imported for local review.",
            "status": review_status,
        },
        "flat_ocr_text": payload.get("flat_ocr_text") or "",
        "markdown_draft": markdown_text,
        "csv_draft": csv_text,
        "json_draft": parsed_json,
        "json_validation": json_validation,
        "database_compatible": json_validation["database_compatible"],
        "detected_schema": json_validation["detected_schema"],
        "target_import": json_validation["target_import"],
        "validation_errors": json_validation["validation_errors"],
        "columns": table_columns_from_rows(rows),
        "rows": rows,
        "review_status": review_status,
        "reviewer": payload.get("reviewer") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": payload.get("notes") or "External table import remains draft until reviewed and promoted to a specific extraction artifact.",
    }
    packet_path = external_table_review_json_path(source_id, page, import_id)
    write_json(packet_path, packet)
    return {
        "ok": True,
        "table_parse": packet,
        "table_parse_json": packet_path.relative_to(wb.ROOT).as_posix(),
        "database_compatible": json_validation["database_compatible"],
        "detected_schema": json_validation["detected_schema"],
        "target_import": json_validation["target_import"],
        "validation_errors": json_validation["validation_errors"],
        "message": (
            "External table review packet imported. JSON is schema-compatible and can be promoted after review."
            if json_validation["database_compatible"]
            else "External table review packet imported. It was not added to SQLite."
        ),
    }


def new_officer_table_artifact(
    source: dict[str, Any], page: int, table_title: str
) -> dict[str, Any]:
    artifact_id = officer_table_artifact_id(source["source_id"], page, table_title)
    return {
        "artifact_id": artifact_id,
        "source_id": source["source_id"],
        "collection": source.get("collection", ""),
        "citation": source.get("citation", ""),
        "title": source.get("title", ""),
        "title_original": source.get("title_original", ""),
        "date": source.get("date", ""),
        "date_certainty": source.get("date_certainty", "unknown"),
        "language": source.get("language", ["ja"]),
        "document_type": source.get("document_type", "secondary_source_table"),
        "local_pdf": source_pdf_reference(source),
        "external_reference": source.get("external_reference", ""),
        "summary_en": "Secondary-scholarship organization officer timeline table extraction.",
        "notes": "Rows are review-gated secondary-source table observations, not primary-source relationship claims.",
        "entities": [],
        "claims": [],
        "keywords": [],
        "provenance": {
            "status": "draft",
            "reviewer": "Reading Desk",
            "extraction_date": datetime.now(timezone.utc).date().isoformat(),
            "method": "selected-region table extraction and human review",
        },
        "extraction_schema_version": "secondary-table-v1",
        "table_schema_version": "organization-officer-timeline-v1",
        "organization_officer_tables": [],
        "organization_officer_terms": [],
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/officer-tables")
async def save_officer_table_extraction(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    payload = await request.json()
    table_payload = payload.get("table") or {}
    if not isinstance(table_payload, dict):
        raise HTTPException(status_code=400, detail="table must be an object")
    table_title = table_payload.get("table_title") or "Organization officer timeline table"
    table_id = table_payload.get("table_id") or f"offtbl_{source_id}_p{page:04d}_01"
    artifact_path = officer_table_artifact_path(source_id, page, table_title)
    artifact = load_json(artifact_path) if artifact_path.exists() else new_officer_table_artifact(source, page, table_title)
    artifact["artifact_id"] = artifact_path.stem
    artifact["source_id"] = source_id
    artifact["extraction_schema_version"] = "secondary-table-v1"
    artifact["table_schema_version"] = "organization-officer-timeline-v1"

    region = payload.get("region") or table_payload.get("crop_region") or {}
    if not isinstance(region, dict):
        raise HTTPException(status_code=400, detail="region must be an object")
    crop_image = table_payload.get("crop_image") or payload.get("crop_image") or ""
    if region and not crop_image:
        region_id = region.get("region_id") or f"reg_{hashlib.sha1(json.dumps(region, sort_keys=True).encode('utf-8')).hexdigest()[:10]}"
        crop_image = crop_page_region(source, page, region, region_id).relative_to(wb.ROOT).as_posix()
        region = {**region, "region_id": region_id, "unit": region.get("unit", "relative")}

    preferred = preferred_ocr_manifest(source_id)
    raw_page_json_path = normalize_project_path(page_json_path_for(preferred[1], page)) if preferred else ""
    now = datetime.now(timezone.utc).isoformat()
    table_record = {
        "table_id": table_id,
        "source_id": source_id,
        "pdf_page": page,
        "printed_page": str(table_payload.get("printed_page") or payload.get("printed_page") or ""),
        "table_title": table_title,
        "organization_name_original": table_payload.get("organization_name_original") or "",
        "organization_entity_id": table_payload.get("organization_entity_id") or "",
        "source_pdf": source_pdf_reference(source),
        "page_image": rendered_page_image_path(source_id, page).relative_to(wb.ROOT).as_posix(),
        "crop_image": crop_image,
        "crop_region": region or {"unit": "relative", "x": 0, "y": 0, "width": 1, "height": 1},
        "ocr_page_json": raw_page_json_path or "",
        "parsing_engine": table_payload.get("parsing_engine") or "manual_reading_desk",
        "review_status": table_payload.get("review_status") or "needs_review",
        "reviewer": table_payload.get("reviewer") or "",
        "reviewed_at": table_payload.get("reviewed_at") or "",
        "notes": table_payload.get("notes") or "",
    }
    if table_record["review_status"] == "reviewed":
        table_record["reviewer"] = table_record["reviewer"] or "local researcher"
        table_record["reviewed_at"] = table_record["reviewed_at"] or now

    terms = []
    for index, term_payload in enumerate(payload.get("terms") or [], start=1):
        if not isinstance(term_payload, dict):
            continue
        term_status = term_payload.get("review_status") or table_record["review_status"]
        term = {
            "term_id": term_payload.get("term_id") or f"{table_id}_term_{index:03d}",
            "table_id": table_id,
            "source_id": source_id,
            "pdf_page": page,
            "printed_page": table_record["printed_page"],
            "person_name_original": term_payload.get("person_name_original") or "",
            "person_name_normalized": term_payload.get("person_name_normalized") or "",
            "person_entity_id": term_payload.get("person_entity_id") or "",
            "organization_name_original": term_payload.get("organization_name_original") or table_record["organization_name_original"],
            "organization_entity_id": term_payload.get("organization_entity_id") or table_record["organization_entity_id"],
            "role_original": term_payload.get("role_original") or "",
            "role_normalized": term_payload.get("role_normalized") or "",
            "date_start": term_payload.get("date_start") or "",
            "date_end": term_payload.get("date_end") or "",
            "era_start": term_payload.get("era_start") or "",
            "era_end": term_payload.get("era_end") or "",
            "status_original": term_payload.get("status_original") or "",
            "overlap_text": term_payload.get("overlap_text") or "",
            "overlap_organizations": term_payload.get("overlap_organizations") or [],
            "evidence_quote": term_payload.get("evidence_quote") or table_title,
            "crop_region_id": region.get("region_id", ""),
            "confidence": term_payload.get("confidence") or "medium",
            "review_status": term_status,
            "reviewer": term_payload.get("reviewer") or table_record["reviewer"],
            "reviewed_at": term_payload.get("reviewed_at") or "",
            "notes": term_payload.get("notes") or "",
        }
        if term["review_status"] == "reviewed":
            term["reviewer"] = term["reviewer"] or "local researcher"
            term["reviewed_at"] = term["reviewed_at"] or now
        terms.append(term)

    artifact["organization_officer_tables"] = [
        table for table in artifact.get("organization_officer_tables", []) if table.get("table_id") != table_id
    ] + [table_record]
    artifact["organization_officer_terms"] = [
        term for term in artifact.get("organization_officer_terms", []) if term.get("table_id") != table_id
    ] + terms

    write_json(artifact_path, artifact)
    try:
        # run_workspace_script("validate_extractions.py")
        # run_workspace_script("build_database.py")
        pass
    except HTTPException:
        raise
    return {
        "ok": True,
        "artifact_id": artifact_path.stem,
        "artifact_path": artifact_path.relative_to(wb.ROOT).as_posix(),
        "table_id": table_id,
        "terms_saved": len(terms),
        "message": "Officer table artifact saved. Reviewed rows were imported into SQLite.",
    }
@router.get("/api/v1/reading/sources/{source_id}/export-text")
def reading_source_export_text(source_id: str) -> dict[str, Any]:
    source = source_by_id(source_id)
    page_count = source.get("page_count", 0) or 0
    pages_text = []
    
    preferred = preferred_ocr_manifest(source_id)
    corrected_info = corrected_ocr_manifest(source_id)
    
    for page in range(1, page_count + 1):
        raw_text = ""
        if preferred is not None:
            ocr_layer, manifest, manifest_path = preferred
            raw_page_json_path = page_json_path_for(manifest, page)
            if raw_page_json_path is not None:
                try:
                    raw_page_json = load_json(resolve_project_relative_path(raw_page_json_path))
                    raw_text = flatten_ocr_text(raw_page_json)
                except Exception:
                    pass
                    
        corrected_text = ""
        if corrected_info:
            corrected_manifest = corrected_info[0]
            corrected_page_json_path = page_json_path_for(corrected_manifest, page)
            if corrected_page_json_path:
                try:
                    corrected_text = flatten_ocr_text(load_json(resolve_project_relative_path(corrected_page_json_path)))
                except Exception:
                    pass
                    
        effective_text = corrected_text or raw_text
        
        tables = (corrected_page_json or {}).get("tables") or (raw_page_json or {}).get("tables") or {}
        if tables:
            import re
            def replace_table_placeholder(match) -> str:
                table_id = match.group(1)
                if table_id in tables and isinstance(tables[table_id], dict):
                    md = tables[table_id].get("markdown", "")
                    return f"\n\n{md.strip()}\n\n"
                return match.group(0)
            effective_text = re.sub(r"\[Table:\s*([a-zA-Z0-9_]+)\]", replace_table_placeholder, effective_text)

        pages_text.append({
            "page": page,
            "text": effective_text
        })
        
    plain_text = ""
    for p in pages_text:
        plain_text += f"--- PAGE {p['page']} ---\n{p['text']}\n\n"
        
    # Compile Markdown Export with notes
    project_id = wb.ACTIVE_PROJECT_ID
    if project_id == "default":
        proj_note_path = wb.ROOT / "db" / "project_note.txt"
    else:
        proj_note_path = wb.ROOT / "projects" / project_id / "project_note.txt"
    project_note = ""
    if proj_note_path.exists():
        project_note = proj_note_path.read_text(encoding="utf-8")
        
    artifact = reading_extraction_artifact(source_id)
    source_notes = artifact.get("notes") or source.get("notes") or ""
    page_notes_dict = artifact.get("page_notes", {})
    
    title = source.get("title_original") or source.get("title") or source_id
    collection = source.get("collection") or ""
    citation = source.get("citation") or ""
    
    markdown_lines = [
        "---",
        f"title: {repr(title)}",
        f"source_id: {repr(source_id)}",
        f"collection: {repr(collection)}",
        f"citation: {repr(citation)}",
    ]
    
    if project_note.strip():
        markdown_lines.append("project_note: |")
        for line in project_note.splitlines():
            markdown_lines.append(f"  {line}")
            
    if source_notes.strip():
        markdown_lines.append("source_note: |")
        for line in source_notes.splitlines():
            markdown_lines.append(f"  {line}")
            
    markdown_lines.append("---")
    markdown_lines.append("")
    markdown_lines.append(f"# {title}")
    markdown_lines.append("")
    
    for p in pages_text:
        page_num = p["page"]
        page_note = page_notes_dict.get(str(page_num)) or page_notes_dict.get(page_num) or ""
        
        markdown_lines.append(f"## Page {page_num}")
        if page_note.strip():
            markdown_lines.append("")
            markdown_lines.append("> **Page Note:**")
            for line in page_note.splitlines():
                markdown_lines.append(f"> {line}")
            markdown_lines.append("")
            
        markdown_lines.append(p["text"])
        markdown_lines.append("")
        
    markdown_text = "\n".join(markdown_lines)
    
    return {
        "source_id": source_id,
        "title": title,
        "pages": pages_text,
        "plain_text": plain_text.strip(),
        "markdown_text": markdown_text.strip()
    }



@router.get("/api/v1/extraction-artifacts/{source_id}")
def get_extraction_artifact(source_id: str) -> dict[str, Any]:
    return reading_extraction_artifact(source_id)


@router.put("/api/v1/extraction-artifacts/{source_id}")
async def update_extraction_artifact(source_id: str, request: Request) -> dict[str, Any]:
    payload = await request.json()
    save_reading_extraction_artifact(source_id, payload)
    return {"ok": True}


@router.put("/api/v1/reading/sources/{source_id}/pages/{page}/note")
async def save_page_note(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    payload = await request.json()
    note_text = payload.get("note", "").strip()
    
    artifact = reading_extraction_artifact(source_id)
    page_notes = artifact.setdefault("page_notes", {})
    page_notes[str(page)] = note_text
    
    save_reading_extraction_artifact(source_id, artifact)
    return {"ok": True}



@router.get("/api/v1/reading/sources/{source_id}/pages/{page}")
def reading_page(source_id: str, page: int) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    source = source_by_id(source_id)
    preferred = preferred_ocr_manifest(source_id)
    ocr_layer = "none"
    manifest_path_text = ""
    raw_page_json_path = None
    raw_text = ""
    raw_page_json = {}
    if preferred is not None:
        ocr_layer, manifest, manifest_path = preferred
        raw_page_json_path = page_json_path_for(manifest, page)
        manifest_path_text = manifest_path.relative_to(wb.ROOT).as_posix()
        if raw_page_json_path is not None:
            raw_page_json = load_json(resolve_project_relative_path(raw_page_json_path))
            raw_text = flatten_ocr_text(raw_page_json)

    if not raw_page_json_path or not raw_text.strip():
        pass

    fallback_path = get_ocr_regions_dir() / source_id / "pages" / f"page_{page:04d}" / "full_page.json"
    if fallback_path.exists():
        try:
            fallback_json = load_json(fallback_path)
            fallback_text = flatten_ocr_text(fallback_json)
            if fallback_text.strip():
                fallback_has_boxes = False
                for block in fallback_json.get("contents", []):
                    if isinstance(block, dict) and "boundingBox" in block:
                        fallback_has_boxes = True
                        break
                    elif isinstance(block, list):
                        for item in block:
                            if isinstance(item, dict) and "boundingBox" in item:
                                fallback_has_boxes = True
                                break
                        if fallback_has_boxes:
                            break
                
                raw_has_boxes = False
                if raw_page_json:
                    for block in raw_page_json.get("contents", []):
                        if isinstance(block, dict) and "boundingBox" in block:
                            raw_has_boxes = True
                            break
                        elif isinstance(block, list):
                            for item in block:
                                if isinstance(item, dict) and "boundingBox" in item:
                                    raw_has_boxes = True
                                    break
                            if raw_has_boxes:
                                break

                manifest_mtime = 0
                if raw_page_json_path:
                    manifest_resolved = resolve_project_relative_path(raw_page_json_path)
                    if manifest_resolved.exists():
                        manifest_mtime = manifest_resolved.stat().st_mtime
                fallback_mtime = fallback_path.stat().st_mtime

                if (not raw_page_json_path or 
                    not raw_text.strip() or 
                    (fallback_has_boxes and not raw_has_boxes) or 
                    fallback_mtime > manifest_mtime):
                    
                    raw_page_json = fallback_json
                    raw_page_json_path = fallback_path.relative_to(wb.ROOT).as_posix()
                    raw_text = fallback_text
                    ocr_layer = "regions_fallback"
        except Exception as e:
            print(f"Error loading regions fallback OCR: {e}")

    corrected_text = ""
    corrected_page_json_path = None
    corrected_page_json = {}
    corrected_info = corrected_ocr_manifest(source_id)
    if corrected_info:
        corrected_manifest = corrected_info[0]
        corrected_page_json_path = page_json_path_for(corrected_manifest, page)
        if corrected_page_json_path:
            corrected_page_json = load_json(resolve_project_relative_path(corrected_page_json_path))
            corrected_text = flatten_ocr_text(corrected_page_json)

    artifact = reading_extraction_artifact(source_id)
    effective_text = corrected_text or raw_text
    page_evidence = [
        evidence for evidence in artifact.get("evidence_quotes", []) if evidence.get("page") == page
    ]
    relationships = [
        claim for claim in artifact.get("relationship_claims", []) if claim.get("page") == page
    ]
    attitudes = [claim for claim in artifact.get("attitude_claims", []) if claim.get("page") == page]
    mentions = [mention for mention in artifact.get("entity_mentions", []) if mention.get("page") == page]
    return {
        "source": {
            "source_id": source_id,
            "title": source.get("title", ""),
            "title_original": source.get("title_original", ""),
            "collection": source.get("collection", ""),
            "citation": source.get("citation", ""),
            "local_pdf": source.get("local_pdf", ""),
            "source_pdf": source_pdf_reference(source),
            "page_count": source.get("page_count"),
            "pdf_status": pdf_diagnostics(source, page=page),
        },
        "page": page,
        "ocr": {
            "layer": ocr_layer,
            "manifest": manifest_path_text,
            "raw_page_json": raw_page_json_path,
            "corrected_page_json": corrected_page_json_path,
            "raw_text": raw_text,
            "corrected_text": corrected_text,
            "effective_text": effective_text,
            "status": "corrected" if corrected_text else "raw",
            "raw_page_json_data": raw_page_json or None,
            "corrected_page_json_data": corrected_page_json or None,
        },
        "artifact_status": artifact.get("provenance", {}).get("status", "draft"),
        "entities": artifact.get("entity_records", []),
        "page_evidence": page_evidence,
        "relationships": relationships,
        "attitudes": attitudes,
        "mentions": mentions,
        "keywords": artifact.get("keywords", []),
        "reading_notes": [
            note for note in artifact.get("reading_notes", []) if note.get("page") == page
        ],
        "page_note": artifact.get("page_notes", {}).get(str(page), ""),
        "candidates": candidate_highlights(artifact, page, effective_text),
        "vocabularies": reading_vocabularies(),
    }


@router.put("/api/v1/reading/sources/{source_id}/pages/{page}/ocr-review")
async def save_ocr_review(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    payload = await request.json()
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Corrected OCR text is required")
    reviewer = payload.get("reviewer") or "local researcher"
    notes = payload.get("notes") or ""
    status = payload.get("status") or "reviewed"

    source = source_by_id(source_id)
    ocr_paths = ocr_paths_for_request(source_id, page, payload)
    raw_page_json_path = ocr_paths["raw_page_json_path"]
    raw_manifest_path = ocr_paths["raw_manifest_path"]
    resolved_raw_path = resolve_project_relative_path(raw_page_json_path) if raw_page_json_path else None
    raw_page_json = load_json(resolved_raw_path) if resolved_raw_path and resolved_raw_path.exists() else {}

    corrected_page_path = get_ocr_corrected_dir() / source_id / "pages" / f"page_{page:04d}.json"
    lines = [line.strip() for line in text.splitlines()]
    
    raw_lines = []
    for block in raw_page_json.get("contents", []):
        if isinstance(block, dict):
            text_val = block.get("text")
            if isinstance(text_val, str):
                raw_lines.append(block)
            continue
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    text_val = item.get("text")
                    if isinstance(text_val, str):
                        raw_lines.append(item)

    contents_list = []
    raw_index = 0
    for index, line in enumerate(lines):
        line_dict = {
            "id": index,
            "text": line,
            "isTextline": "true",
            "isCorrectedOcr": "true",
        }
        if line.strip():
            if raw_index < len(raw_lines):
                orig = raw_lines[raw_index]
                if "boundingBox" in orig:
                    line_dict["boundingBox"] = orig["boundingBox"]
                if "isVertical" in orig:
                    line_dict["isVertical"] = orig["isVertical"]
                if "class_index" in orig:
                    line_dict["class_index"] = orig["class_index"]
                if "confidence" in orig:
                    line_dict["confidence"] = orig["confidence"]
                raw_index += 1
        contents_list.append(line_dict)

    corrected_page_json = {
        "contents": [contents_list],
        "imginfo": raw_page_json.get("imginfo", {}),
        "tables": payload.get("tables") or raw_page_json.get("tables", {}),
        "corrected_ocr": {
            "page": page,
            "reviewer": reviewer,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "notes": notes,
            "original_ocr_page_json": raw_page_json_path,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
    }
    if "region_ocr" in raw_page_json:
        corrected_page_json["region_ocr"] = raw_page_json["region_ocr"]
    write_json(corrected_page_path, corrected_page_json)

    manifest_path = get_ocr_corrected_dir() / source_id / "manifest.json"
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
            "ocr_engine": "corrected OCR text",
            "ocr_engine_path": "artifacts/ocr/corrected",
            "ocr_settings": {
                "base_manifest": to_project_relative_path(raw_manifest_path) if raw_manifest_path else "",
                "format": "corrected-page-json",
            },
            "status": "reviewed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": reviewer,
            "source_pdf": source_pdf_reference(source),
        }
    relative_page_path = to_project_relative_path(corrected_page_path)
    page_map = {manifest_page: path for manifest_page, path in zip(manifest.get("pages", []), manifest.get("page_json", []))}
    page_map[page] = relative_page_path
    pages = sorted(page_map)
    manifest["pages"] = pages
    manifest["page_json"] = [page_map[manifest_page] for manifest_page in pages]
    manifest["page_range"] = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
    manifest["status"] = status
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["reviewer"] = reviewer
    write_json(manifest_path, manifest)
    saved_at = corrected_page_json["corrected_ocr"]["reviewed_at"]
    file_exists = corrected_page_path.exists()
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "corrected_page_json": relative_page_path,
        "corrected_ocr_path": relative_page_path,
        "corrected_ocr_page_json": relative_page_path,
        "manifest": to_project_relative_path(manifest_path),
        "saved_at": saved_at,
        "text_length": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "file_exists": file_exists,
        "debug": {
            "save_path": relative_page_path,
            "file_exists": file_exists,
            "source_id": source_id,
            "page": page,
            "text_length": len(text),
        }
        if payload.get("debug")
        else None,
        "message": f"Corrected OCR saved: {relative_page_path}",
    }


@router.post("/api/v1/reading/sources/{source_id}/pages/{page}/evidence")
async def save_reading_evidence(source_id: str, page: int, request: Request) -> dict[str, Any]:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be a positive integer")
    payload = await request.json()
    kind = payload.get("kind")
    if kind not in {"quote", "keyword", "entity", "place", "relationship", "attitude", "claim", "note"}:
        raise HTTPException(status_code=400, detail="Evidence kind is required")

    source = source_by_id(source_id)
    ocr_paths = ocr_paths_for_request(source_id, page, payload)
    raw_page_json_path = ocr_paths["raw_page_json_path"]
    corrected_page_json_path = ocr_paths["corrected_page_json_path"]
    effective_ocr_path = ocr_paths["effective_ocr_path"]
    if kind == "quote" or (kind == "note" and payload.get("quote")):
        require_existing_ocr_path(effective_ocr_path)
    if not raw_page_json_path:
        raw_page_json_path = effective_ocr_path

    artifact = reading_extraction_artifact(source_id)
    include_page_in_scope(artifact, page)
    quote = (payload.get("quote") or "").strip()
    note = payload.get("note") or ""
    confidence = payload.get("confidence") or "medium"
    payload_evidence_id = payload.get("evidence_id") or ""
    evidence: dict[str, Any] | None = None
    structured_kinds = {"keyword", "entity", "place", "relationship", "attitude", "claim"}
    if kind in structured_kinds:
        evidence = resolve_evidence(artifact, source_id, page, payload_evidence_id, quote or None)
        quote = evidence.get("quote", "")
    changed = kind

    if kind == "note":
        if payload_evidence_id:
            evidence = resolve_evidence(artifact, source_id, page, payload_evidence_id, quote or None)
            quote = evidence.get("quote", "")
        notes = artifact.setdefault("reading_notes", [])
        notes.append(
            {
                "note_id": next_id(notes, "note_id", f"rd_{source_id}_p{page:04d}_note"),
                "source_id": source_id,
                "page": page,
                "text": note or quote,
                "quote": quote,
                "evidence_id": payload_evidence_id,
                "ocr_page_json": effective_ocr_path or raw_page_json_path,
                "corrected_ocr_page_json": corrected_page_json_path or "",
                "source_pdf": source_pdf_reference(source),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    elif kind == "keyword":
        keyword = (payload.get("keyword") or quote).strip()
        if not keyword:
            raise HTTPException(status_code=400, detail="Keyword text is required")
        keywords = artifact.setdefault("keywords", [])
        if keyword not in keywords:
            keywords.append(keyword)
        keyword_mentions = artifact.setdefault("keyword_mentions", [])
        keyword_mentions.append(
            {
                "keyword_mention_id": next_id(keyword_mentions, "keyword_mention_id", f"rd_{source_id}_p{page:04d}_kw"),
                "source_id": source_id,
                "page": page,
                "keyword": keyword,
                "evidence_id": evidence["evidence_id"] if evidence else payload_evidence_id,
                "quote": quote,
                "confidence": confidence,
                "note": note,
            }
        )
    else:
        if kind == "quote":
            evidence_id = ensure_evidence(
                artifact,
                source,
                page,
                quote,
                raw_page_json_path,
                corrected_page_json_path,
                note,
            )
        else:
            evidence_id = evidence["evidence_id"] if evidence else payload_evidence_id
        if kind in {"entity", "place"}:
            entity_payload = payload.get("entity") or {}
            name = entity_payload.get("name") or quote
            entity_id = ensure_entity(
                artifact,
                entity_payload.get("entity_id"),
                name,
                "place" if kind == "place" else entity_payload.get("entity_type") or "person",
                entity_payload.get("aliases") or [],
                entity_payload.get("notes") or note,
            )
            add_mention(artifact, entity_id, source_id, page, name, evidence_id, confidence, note)
        elif kind == "claim":
            claim_text = (payload.get("claim", {}) or {}).get("text") or quote
            claims = artifact.setdefault("claims", [])
            claims.append(
                {
                    "claim_id": next_id(claims, "claim_id", f"rd_{source_id}_p{page:04d}_claim"),
                    "source_id": source_id,
                    "page": page,
                    "text": claim_text,
                    "evidence": quote,
                    "evidence_id": evidence_id,
                    "quote": quote,
                    "confidence": confidence,
                    "note": note,
                    "extraction_status": "draft",
                    "ocr_page_json": corrected_page_json_path or raw_page_json_path,
                    "source_pdf": source_pdf_reference(source),
                }
            )
        elif kind == "relationship":
            relationship = payload.get("relationship") or {}
            subject = relationship.get("subject") or {}
            object_record = relationship.get("object") or {}
            subject_id = ensure_entity(
                artifact,
                subject.get("entity_id"),
                subject.get("name") or "",
                subject.get("entity_type") or "person",
                subject.get("aliases") or [],
            )
            object_id = ensure_entity(
                artifact,
                object_record.get("entity_id"),
                object_record.get("name") or "",
                object_record.get("entity_type") or "person",
                object_record.get("aliases") or [],
            )
            relation_type = relationship.get("relation_type") or payload.get("relation_type")
            if not relation_type:
                raise HTTPException(status_code=400, detail="Relationship type is required")
            claims = artifact.setdefault("relationship_claims", [])
            claims.append(
                {
                    "relationship_id": next_id(claims, "relationship_id", f"rd_{source_id}_p{page:04d}_rel"),
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
        elif kind == "attitude":
            attitude = payload.get("attitude") or {}
            speaker = attitude.get("speaker") or {}
            target = attitude.get("target") or {}
            speaker_id = ensure_entity(
                artifact,
                speaker.get("entity_id"),
                speaker.get("name") or "",
                speaker.get("entity_type") or "person",
                speaker.get("aliases") or [],
            )
            target_id = ensure_entity(
                artifact,
                target.get("entity_id"),
                target.get("name") or "",
                target.get("entity_type") or "person",
                target.get("aliases") or [],
            )
            attitude_type = attitude.get("attitude_type") or payload.get("attitude_type")
            polarity = attitude.get("polarity") or payload.get("polarity")
            if not attitude_type or not polarity:
                raise HTTPException(status_code=400, detail="Attitude type and polarity are required")
            claims = artifact.setdefault("attitude_claims", [])
            claims.append(
                {
                    "attitude_id": next_id(claims, "attitude_id", f"rd_{source_id}_p{page:04d}_att"),
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

    save_reading_extraction_artifact(source_id, artifact)
    return {
        "ok": True,
        "source_id": source_id,
        "page": page,
        "kind": changed,
        "evidence_id": evidence_id if "evidence_id" in locals() else payload_evidence_id,
        "quote": quote,
        "message": "Reading Desk evidence saved and database rebuilt.",
    }


@router.get("/api/v1/reading/search-ocr")
def search_ocr_keywords(q: str = Query(min_length=1)) -> list[dict[str, Any]]:
    query = q.lower()
    results = []
    
    # Get all sources from JSON catalog to match titles
    try:
        sources_list = wb.load_sources()
        source_map = {s["source_id"]: (s.get("title_original") or s.get("title") or s["source_id"]) for s in sources_list}
    except Exception:
        source_map = {}
    
    # corrected first, then raw
    corrected_dir = get_ocr_corrected_dir()
    raw_dir = get_ocr_raw_dir()
    
    pages_to_search = {}
    
    if corrected_dir.exists():
        for source_path in corrected_dir.iterdir():
            if source_path.is_dir():
                source_id = source_path.name
                pages_dir = source_path / "pages"
                if pages_dir.exists():
                    for page_file in pages_dir.glob("page_*.json"):
                        try:
                            page_num = int(page_file.stem.split("_")[1])
                            pages_to_search[(source_id, page_num)] = page_file
                        except Exception:
                            continue
                            
    if raw_dir.exists():
        for source_path in raw_dir.iterdir():
            if source_path.is_dir():
                source_id = source_path.name
                pages_dir = source_path / "pages"
                if pages_dir.exists():
                    for page_file in pages_dir.glob("page_*.json"):
                        try:
                            page_num = int(page_file.stem.split("_")[1])
                            key = (source_id, page_num)
                            if key not in pages_to_search:
                                pages_to_search[key] = page_file
                        except Exception:
                            continue
                            
    for (source_id, page_num), file_path in pages_to_search.items():
        try:
            page_json = load_json(file_path)
            text = flatten_ocr_text(page_json)
            if query in text.lower():
                idx = text.lower().find(query)
                start = max(0, idx - 40)
                end = min(len(text), idx + len(query) + 40)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                
                results.append({
                    "source_id": source_id,
                    "source_title": source_map.get(source_id, source_id),
                    "page": page_num,
                    "snippet": snippet,
                })
        except Exception:
            continue
            
    # Sort results by source_id, page
    results.sort(key=lambda r: (r["source_id"], r["page"]))
    return results[:100]

