from __future__ import annotations

from typing import Any

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import FileResponse

import backend.app.services.workbench as wb
from backend.app.services.workbench import *

router = APIRouter()


def source_by_id(*args: Any, **kwargs: Any) -> Any:
    return wb.source_by_id(*args, **kwargs)


def biography_sources(*args: Any, **kwargs: Any) -> Any:
    return wb.biography_sources(*args, **kwargs)


async def run_batch_ocr_page(*args: Any, **kwargs: Any) -> Any:
    return await wb.run_batch_ocr_page(*args, **kwargs)


def save_reading_extraction_artifact(*args: Any, **kwargs: Any) -> Any:
    return wb.save_reading_extraction_artifact(*args, **kwargs)

async def create_batch_biography_run_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source_id = payload.get("source_id") or "raw_ee2029d2f4ef"
    all_sources = bool(payload.get("all_sources", False))
    run_ocr = bool(payload.get("run_ocr", False))
    engine_id = payload.get("ocr_engine") or "ndlocr_lite"
    max_pages = payload.get("max_pages")
    page_scope = payload.get("page_scope") or "available_ocr"
    analysis_mode = payload.get("analysis_mode") or "relevant_evidence"
    if analysis_mode not in {"relevant_evidence", "wide_entities"}:
        raise HTTPException(status_code=400, detail="analysis_mode must be relevant_evidence or wide_entities")
    analysis_engine = payload.get("analysis_engine") or "worker_ai_with_local_fallback"
    if analysis_engine not in {"worker_ai", "worker_ai_with_local_fallback", "local_fallback"}:
        raise HTTPException(status_code=400, detail="analysis_engine must be worker_ai, worker_ai_with_local_fallback, or local_fallback")
    worker_skill_id = payload.get("worker_skill_id") or ("entity_extraction" if analysis_mode == "wide_entities" else "relevant_passage_selection")
    requested_source_skill_id = payload.get("source_skill_id") or None
    max_quote_candidates = int(payload.get("max_quote_candidates") or (12 if analysis_mode == "wide_entities" else 3))
    worker_config = worker_config_from_env()
    temporary_ocr_text_path_value = payload.get("temporary_ocr_text_path") or payload.get("ocr_text_path")
    if temporary_ocr_text_path_value and page_scope == "available_ocr":
        page_scope = "temporary_text"
    if page_scope not in {"available_ocr", "full_pdf", "temporary_text"}:
        raise HTTPException(status_code=400, detail="page_scope must be available_ocr, full_pdf, or temporary_text")
    temporary_ocr_text_path = resolve_temporary_ocr_text_path(temporary_ocr_text_path_value) if temporary_ocr_text_path_value else None
    if page_scope == "temporary_text" and not temporary_ocr_text_path:
        raise HTTPException(status_code=400, detail="temporary_text page_scope requires temporary_ocr_text_path")
    if temporary_ocr_text_path and all_sources:
        raise HTTPException(status_code=400, detail="Temporary OCR text runs must target one source")
    selected_sources = biography_sources() if all_sources else [source_by_id(source_id)]
    if not selected_sources:
        raise HTTPException(status_code=404, detail="No biography sources found")

    seed = json.dumps(
        {
            "source_ids": [source["source_id"] for source in selected_sources],
            "run_ocr": run_ocr,
            "engine_id": engine_id,
            "page_scope": page_scope,
            "temporary_ocr_text_path": to_project_relative_path(temporary_ocr_text_path) if temporary_ocr_text_path else "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    run_id = payload.get("run_id") or f"bio_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8]}"
    run_root = batch_run_root(run_id)
    if run_root.exists():
        raise HTTPException(status_code=409, detail=f"Batch run already exists: {run_id}")

    manifest = {
        "run_id": run_id,
        "kind": "batch-biographies",
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "run_ocr": run_ocr,
        "ocr_engine": engine_id,
        "page_scope": page_scope,
        "temporary_ocr_text_path": to_project_relative_path(temporary_ocr_text_path) if temporary_ocr_text_path else "",
        "analysis_engine": analysis_engine,
        "analysis_mode": analysis_mode,
        "worker_skill_id": worker_skill_id,
        "source_skill_id": requested_source_skill_id or "",
        "worker_provider": worker_config.provider,
        "worker_model": worker_config.model,
        "source_ids": [source["source_id"] for source in selected_sources],
        "sources": [],
        "counts": {},
        "notes": "Provisional batch review packets. Nothing here is durable evidence until promoted.",
    }
    write_json(batch_run_path(run_id), manifest)

    for source in selected_sources:
        temporary_pages: dict[int, dict[str, str]] = {}
        if temporary_ocr_text_path:
            temporary_pages = parse_page_marked_ocr_text(temporary_ocr_text_path.read_text(encoding="utf-8"))
        pages = sorted(temporary_pages) if page_scope == "temporary_text" and temporary_pages else batch_source_pages(source, page_scope)
        if isinstance(max_pages, int) and max_pages > 0:
            pages = pages[:max_pages]
        source_summary = {
            "source_id": source["source_id"],
            "title": source.get("title", ""),
            "title_original": source.get("title_original", ""),
            "page_count": len(pages),
            "pages": pages,
        }
        manifest["sources"].append(source_summary)
        write_json(batch_run_path(run_id), manifest)
        ocr_by_page: dict[int, dict[str, Any]] = {}
        if temporary_ocr_text_path:
            ocr_by_page.update(write_temporary_text_ocr_records(run_id, source, temporary_ocr_text_path, pages))
        for page in pages:
            if page in ocr_by_page:
                continue
            existing_ocr = best_ocr_for_page(source["source_id"], page)
            if existing_ocr["ocr_status"] == "missing" and run_ocr:
                existing_ocr = await run_batch_ocr_page(run_id, source, page, engine_id)
            ocr_by_page[page] = existing_ocr
        repeated_texts = repeated_ocr_texts_from_records(list(ocr_by_page.values()))
        lexicon = network_entity_lexicon()
        article_context: dict[str, Any] | None = None
        source_skill_id = requested_source_skill_id or source_skill_id_for_worker(source)
        for page in pages:
            article_context = compiled_volume_context_for_page(
                page,
                ocr_by_page.get(page, {}).get("ocr_text", ""),
                article_context,
            )
            packet = create_batch_page_packet(
                run_id,
                source,
                page,
                ocr_by_page.get(page),
                lexicon=lexicon,
                repeated_texts=repeated_texts,
                article_context=article_context,
            )
            packet = await enrich_packet_with_worker_candidates(
                packet,
                source,
                {**ocr_by_page.get(page, {}), "article_context": article_context},
                analysis_engine=analysis_engine,
                analysis_mode=analysis_mode,
                worker_skill_id=worker_skill_id,
                source_skill_id=source_skill_id,
                max_quote_candidates=max_quote_candidates,
            )
            write_json(batch_page_path(run_id, source["source_id"], page), packet)

    manifest["status"] = "completed"
    write_json(batch_run_path(run_id), manifest)
    manifest = refresh_batch_manifest_counts(run_id)
    return {"ok": True, "run": manifest, "message": f"Batch biography run created: {run_id}"}


@router.post("/api/v1/batches/biographies/runs")
async def create_batch_biography_run(request: Request) -> dict[str, Any]:
    return await create_batch_biography_run_from_payload(await request.json())


@router.post("/api/v1/batches/biographies/runs/kako-rokujunenseki")
async def create_kako_rokujunenseki_batch_run(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload.update(
        {
            "source_id": "raw_65bec5fd12fd",
            "page_scope": "full_pdf",
            "run_ocr": True,
        }
    )
    return await create_batch_biography_run_from_payload(payload)


@router.post("/api/v1/batches/biographies/runs/toden-hitchuroku")
async def create_toden_hitchuroku_batch_run(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload.update(
        {
            "source_id": "raw_8ab4cdc4678e",
            "page_scope": "temporary_text",
            "run_ocr": False,
            "temporary_ocr_text_path": "sources/raw/Electricity and energy history in Japan/Biographies/OCR text/東電筆誅錄.txt",
        }
    )
    return await create_batch_biography_run_from_payload(payload)


@router.get("/api/v1/batches/biographies/runs")
def list_batch_biography_runs() -> list[dict[str, Any]]:
    runs = []
    for path in sorted(get_batch_review_dir().glob("*/manifest.json"), reverse=True):
        try:
            runs.append(refresh_batch_manifest_counts(path.parent.name))
        except HTTPException:
            continue
    return runs


@router.get("/api/v1/batches/biographies/runs/{run_id}")
def get_batch_biography_run(run_id: str) -> dict[str, Any]:
    return refresh_batch_manifest_counts(run_id)


@router.delete("/api/v1/batches/biographies/runs/{run_id}")
def delete_batch_biography_run(run_id: str) -> dict[str, Any]:
    run_root = batch_run_root(run_id)
    if not run_root.exists() or not (run_root / "manifest.json").exists():
        raise HTTPException(status_code=404, detail="Batch biography run not found")
    shutil.rmtree(run_root)
    return {
        "ok": True,
        "run_id": run_id,
        "runs": list_batch_biography_runs(),
        "message": f"Deleted provisional batch run: {run_id}",
    }


@router.get("/api/v1/batches/biographies/runs/{run_id}/pages")
def list_batch_biography_pages(
    run_id: str,
    source_id: str | None = None,
    page: int | None = None,
    candidate_type: str | None = None,
    status: str | None = None,
    ocr_status: str | None = None,
    include_all: bool = False,
) -> list[dict[str, Any]]:
    load_batch_manifest(run_id)
    summaries = []
    for path in sorted((get_batch_review_dir() / run_id / "sources").glob("*/pages/page_*.json")):
        packet = enrich_batch_packet_ocr_state(load_json(path))
        if source_id and packet.get("source_id") != source_id:
            continue
        if page is not None and packet.get("page") != page:
            continue
        if ocr_status and packet.get("ocr_status") != ocr_status:
            continue
        candidates = packet.get("quote_candidates", []) + packet.get("structured_candidates", [])
        has_relevant_candidates = packet.get("network_review_status") == "network_passages_found" or bool(candidates)
        if not include_all and not has_relevant_candidates:
            continue
        if candidate_type and not any((candidate.get("kind") or candidate.get("candidate_type")) == candidate_type for candidate in candidates):
            continue
        if status and not any(candidate.get("review_status") == status for candidate in candidates):
            continue
        summaries.append(batch_page_summary(packet))
    return summaries


@router.get("/api/v1/batches/biographies/runs/{run_id}/pages/{source_id}/{page}")
def get_batch_biography_page(run_id: str, source_id: str, page: int) -> dict[str, Any]:
    load_batch_manifest(run_id)
    path = batch_page_path(run_id, source_id, page)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Batch page packet not found")
    return enrich_batch_packet_ocr_state(load_json(path))


@router.post("/api/v1/batches/biographies/runs/{run_id}/pages/{source_id}/{page}/sync-ocr")
def sync_batch_biography_page_ocr(run_id: str, source_id: str, page: int) -> dict[str, Any]:
    load_batch_manifest(run_id)
    path = batch_page_path(run_id, source_id, page)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Batch page packet not found")
    current = enrich_batch_packet_ocr_state(load_json(path))
    latest = latest_ocr_for_page(source_id, page)
    if not latest.get("ocr_page_json") or not latest.get("ocr_text"):
        current["ocr_sync_message"] = "No newer OCR text is available for this page."
        write_json(path, current)
        return {"ok": True, "changed": False, "page": current, "message": current["ocr_sync_message"]}

    if batch_packet_uses_local_ocr_edits(current):
        current["latest_available_ocr_layer"] = latest.get("ocr_layer", "")
        current["latest_available_ocr_page_json"] = latest.get("ocr_page_json", "")
        current["latest_available_ocr_manifest"] = latest.get("ocr_manifest", "")
        current["latest_available_ocr_status"] = latest.get("ocr_status", "")
        current["latest_available_text_length"] = len(latest.get("ocr_text", ""))
        current["ocr_is_stale"] = latest.get("ocr_page_json") != current.get("displayed_ocr_page_json")
        current["ocr_sync_message"] = "Corrected OCR available, batch OCR has local edits."
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, current)
        return {"ok": True, "changed": False, "page": current, "message": current["ocr_sync_message"]}

    source = source_by_id(source_id)
    artifact = reading_extraction_artifact(source_id)
    quote_candidates, structured_candidates, network_status = generate_batch_candidates(source_id, page, source, latest, artifact)
    current.update(
        {
            "ocr_layer": latest["ocr_layer"],
            "ocr_page_json": latest["ocr_page_json"],
            "ocr_manifest": latest["ocr_manifest"],
            "ocr_text": latest["ocr_text"],
            "ocr_status": latest["ocr_status"],
            "displayed_ocr_layer": latest["ocr_layer"],
            "displayed_ocr_page_json": latest["ocr_page_json"],
            "displayed_ocr_text": latest["ocr_text"],
            "latest_available_ocr_layer": latest["ocr_layer"],
            "latest_available_ocr_page_json": latest["ocr_page_json"],
            "latest_available_ocr_manifest": latest["ocr_manifest"],
            "latest_available_ocr_status": latest["ocr_status"],
            "latest_available_text_length": len(latest["ocr_text"]),
            "ocr_is_stale": False,
            "ocr_review_status": "candidate",
            "ocr_sync_message": f"Batch page now shows {latest['ocr_layer']} OCR.",
            "quote_candidates": quote_candidates,
            "network_passage_candidates": quote_candidates,
            "network_review_status": network_status,
            "structured_candidates": structured_candidates,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(path, current)
    manifest = refresh_batch_manifest_counts(run_id)
    return {"ok": True, "changed": True, "page": current, "run": manifest, "message": current["ocr_sync_message"]}


@router.put("/api/v1/batches/biographies/runs/{run_id}/pages/{source_id}/{page}")
async def update_batch_biography_page(run_id: str, source_id: str, page: int, request: Request) -> dict[str, Any]:
    load_batch_manifest(run_id)
    path = batch_page_path(run_id, source_id, page)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Batch page packet not found")
    current = enrich_batch_packet_ocr_state(load_json(path))
    payload = await request.json()
    allowed_statuses = {"candidate", "approved", "rejected", "edited", "promoted"}
    previous_ocr_text = current.get("ocr_text", "")
    for field in ("ocr_text", "ocr_status", "review_status", "ocr_review_status"):
        if field in payload:
            current[field] = payload[field]
    if "ocr_text" in payload:
        current["displayed_ocr_text"] = payload["ocr_text"]
        if payload["ocr_text"] != previous_ocr_text:
            current["ocr_review_status"] = payload.get("ocr_review_status") or "edited"
            current["displayed_ocr_layer"] = "batch_edited"
    for field in ("quote_candidates", "structured_candidates"):
        if field in payload:
            records = payload[field]
            if not isinstance(records, list):
                raise HTTPException(status_code=400, detail=f"{field} must be a list")
            for candidate in records:
                status = candidate.get("review_status", "candidate")
                if status not in allowed_statuses:
                    raise HTTPException(status_code=400, detail=f"Invalid candidate review_status: {status}")
            current[field] = records
    current = enrich_batch_packet_ocr_state(current)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, current)
    manifest = refresh_batch_manifest_counts(run_id)
    return {"ok": True, "page": current, "run": manifest, "message": "Batch review page saved."}


@router.post("/api/v1/batches/biographies/runs/{run_id}/promote")
async def promote_batch_biography_run(run_id: str, request: Request) -> dict[str, Any]:
    load_batch_manifest(run_id)
    payload = await request.json()
    only_source_id = payload.get("source_id") or ""
    only_page = payload.get("page")
    promoted: dict[str, int] = {}
    promoted_candidate_ids: list[str] = []
    skipped_details: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}

    page_paths = sorted((get_batch_review_dir() / run_id / "sources").glob("*/pages/page_*.json"))
    for path in page_paths:
        packet = load_json(path)
        source_id = packet["source_id"]
        page = int(packet["page"])
        if only_source_id and source_id != only_source_id:
            continue
        if isinstance(only_page, int) and page != only_page:
            continue
        source = source_by_id(source_id)
        artifact = artifacts.setdefault(source_id, reading_extraction_artifact(source_id))
        include_page_in_scope(artifact, page)
        evidence_id_by_quote_candidate: dict[str, str] = {}
        quote_candidates = {candidate.get("candidate_id"): candidate for candidate in packet.get("quote_candidates", [])}

        def record_promotion(candidate: dict[str, Any], result: dict[str, Any]) -> None:
            kind = result["kind"]
            promoted[kind] = promoted.get(kind, 0) + 1
            candidate["review_status"] = "promoted"
            candidate["promoted_at"] = datetime.now(timezone.utc).isoformat()
            candidate["promotion_message"] = "Promoted to extraction JSON."
            candidate_id = candidate.get("candidate_id", "")
            if candidate_id:
                promoted_candidate_ids.append(candidate_id)

        def record_skip(candidate: dict[str, Any], result: dict[str, Any]) -> None:
            candidate["promotion_skip_reason"] = result.get("reason", "skipped")
            skipped_details.append(result)

        for candidate in packet.get("quote_candidates", []):
            if candidate.get("review_status") != "approved":
                continue
            result = promote_batch_candidate(artifact, source, packet, candidate, evidence_id_by_quote_candidate)
            if result.get("ok"):
                record_promotion(candidate, result)
            else:
                record_skip(candidate, result)
        for candidate in packet.get("structured_candidates", []):
            if candidate.get("review_status") != "approved":
                continue
            parent_quote_id = candidate.get("quote_candidate_id")
            parent_quote = quote_candidates.get(parent_quote_id)
            if not parent_quote or parent_quote.get("review_status") == "rejected":
                record_skip(
                    candidate,
                    {
                        "ok": False,
                        "kind": candidate.get("kind") or candidate.get("candidate_type") or "unknown",
                        "candidate_id": candidate.get("candidate_id", ""),
                        "reason": "parent_quote_rejected_or_missing",
                        "source_id": source_id,
                        "page": page,
                    },
                )
                continue
            if parent_quote_id not in evidence_id_by_quote_candidate:
                parent_result = promote_batch_candidate(artifact, source, packet, parent_quote, evidence_id_by_quote_candidate)
                if parent_result.get("ok"):
                    if parent_quote.get("review_status") != "promoted":
                        record_promotion(parent_quote, parent_result)
                    else:
                        parent_quote["promotion_message"] = "Already promoted; parent evidence reused."
                else:
                    record_skip(candidate, {**parent_result, "candidate_id": candidate.get("candidate_id", ""), "reason": parent_result.get("reason") or "parent_quote_rejected_or_missing"})
                    continue
            if parent_quote.get("quote"):
                candidate["quote"] = parent_quote["quote"]
            result = promote_batch_candidate(artifact, source, packet, candidate, evidence_id_by_quote_candidate)
            if result.get("ok"):
                record_promotion(candidate, result)
            else:
                record_skip(candidate, result)
        write_json(path, packet)

    for source_id, artifact in artifacts.items():
        save_reading_extraction_artifact(source_id, artifact)
    manifest = refresh_batch_manifest_counts(run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "promoted": promoted,
        "promoted_candidate_ids": promoted_candidate_ids,
        "skipped": len(skipped_details),
        "skipped_details": skipped_details,
        "run": manifest,
        "message": f"Promoted approved batch candidates from {run_id}.",
    }


@router.get("/api/batch/check-gliner")
def check_gliner_endpoint() -> dict[str, Any]:
    try:
        from gliner import GLiNER
        from glirel import GLiREL
        import loguru
        
        # Also check if model weights are pre-downloaded/cached
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
            from pathlib import Path
            cache_dir = Path(HF_HUB_CACHE)
            gliner_dir = cache_dir / "models--urchade--gliner_multi-v2.1"
            glirel_dir = cache_dir / "models--jackboyla--glirel-large-v0"
            if not (gliner_dir.exists() and glirel_dir.exists()):
                return {"installed": False}
        except Exception:
            return {"installed": False}
            
        return {"installed": True}
    except ImportError:
        return {"installed": False}


@router.post("/api/batch/extract")
async def batch_extract(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    payload = await request.json()
    source_id = payload.get("source_id", "")
    ocr_engine = payload.get("ocr_engine", "ndlocr_lite")
    nlp_method = payload.get("nlp_method", "gliner")
    entity_labels = payload.get("entity_labels", [])
    relation_labels = payload.get("relation_labels", [])
    slm_prompt = payload.get("slm_prompt", "")
    llm_prompt = payload.get("llm_prompt", "")
    
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
        
    # Check that source exists
    source_by_id(source_id)
    run_id = f"run_ext_{int(datetime.now(timezone.utc).timestamp())}"
    
    # Start background task
    background_tasks.add_task(
        run_batch_nlp_extraction,
        run_id,
        source_id,
        ocr_engine,
        nlp_method,
        entity_labels,
        relation_labels,
        slm_prompt,
        llm_prompt
    )
    
    return {
        "ok": True,
        "run_id": run_id,
        "message": f"Batch extraction run {run_id} started in the background."
    }
