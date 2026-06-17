from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = ROOT / "docs" / "skills"


@dataclass(frozen=True)
class WorkerConfig:
    available: bool
    provider: str
    model: str
    api_key_present: bool
    base_url: str


def worker_config_from_env() -> WorkerConfig:
    requested_provider = os.getenv("KOSHU_WORKER_PROVIDER", "auto").strip().lower() or "auto"
    poe_key = os.getenv("POE_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    poe_model = os.getenv("POE_WORKER_MODEL", "").strip()
    openrouter_model = os.getenv("OPENROUTER_WORKER_MODEL", "").strip()
    shared_model = os.getenv("KOSHU_WORKER_MODEL", "").strip()

    if requested_provider == "poe" or (requested_provider == "auto" and poe_key):
        provider = "poe"
        api_key = poe_key
        model = poe_model or shared_model
        base_url = os.getenv("POE_BASE_URL", "https://api.poe.com/v1/chat/completions").strip()
    else:
        provider = "openrouter"
        api_key = openrouter_key
        model = openrouter_model or shared_model
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip()
    return WorkerConfig(
        available=bool(api_key and model),
        provider=provider,
        model=model,
        api_key_present=bool(api_key),
        base_url=base_url,
    )


def available_skill_docs(skill_root: Path = SKILL_ROOT) -> list[dict[str, str]]:
    if not skill_root.exists():
        return []
    docs: list[dict[str, str]] = []
    for path in sorted(skill_root.rglob("*.md")):
        rel = path.relative_to(skill_root).as_posix()
        docs.append({"skill_id": rel.removesuffix(".md"), "path": rel})
    return docs


def load_skill_doc(skill_id: str, skill_root: Path = SKILL_ROOT) -> str:
    safe_parts = [part for part in skill_id.replace("\\", "/").split("/") if part and part not in {".", ".."}]
    if not safe_parts:
        raise ValueError("skill_id is required")
    path = skill_root.joinpath(*safe_parts)
    if path.suffix != ".md":
        path = path.with_suffix(".md")
    resolved = path.resolve()
    root = skill_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("skill path must stay inside docs/skills") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"Skill doc not found: {skill_id}")
    return resolved.read_text(encoding="utf-8")


def strip_json_markdown(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def parse_worker_json(text: str) -> dict[str, Any]:
    cleaned = strip_json_markdown(text)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Worker output must be a JSON object")
    return value


def _normalize_passage_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" 　")


def split_text_into_passages(text: str, max_chars: int = 320) -> list[str]:
    passages: list[str] = []
    for raw_line in text.splitlines():
        line = _normalize_passage_text(raw_line)
        if not line:
            continue
        pieces = re.split(r"(?<=[。！？!?])", line)
        current = ""
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if current and len(current) + len(piece) > max_chars:
                passages.append(current)
                current = piece
            else:
                current = f"{current}{piece}" if current else piece
        if current:
            passages.append(current)
    expanded: list[str] = []
    for passage in passages:
        if len(passage) <= max_chars * 2:
            expanded.append(passage)
            continue
        for start in range(0, len(passage), max_chars):
            chunk = passage[start : start + max_chars].strip()
            if chunk:
                expanded.append(chunk)
    return expanded


def build_passage_packets(
    source_id: str,
    page: int,
    text: str,
    *,
    context_window: int = 2,
    max_chars: int = 320,
    article_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    passages = split_text_into_passages(text, max_chars=max_chars)
    packets: list[dict[str, Any]] = []
    for index, passage in enumerate(passages):
        digest = hashlib.sha1(f"{source_id}:{page}:{index}:{passage}".encode("utf-8")).hexdigest()[:10]
        start = max(0, index - context_window)
        end = min(len(passages), index + context_window + 1)
        packets.append(
            {
                "passage_id": f"pass_{source_id}_p{page:04d}_{index + 1:04d}_{digest}",
                "source_id": source_id,
                "page": page,
                "passage_index": index + 1,
                "text": passage,
                "previous_context": passages[start:index],
                "next_context": passages[index + 1 : end],
                "article_context": article_context or {},
            }
        )
    return packets


def quote_from_span(packet: dict[str, Any], start: Any, end: Any) -> tuple[str, dict[str, Any]]:
    text = packet.get("text", "")
    try:
        start_int = int(start)
        end_int = int(end)
    except (TypeError, ValueError):
        return "", {"ok": False, "reason": "invalid_span_offsets"}
    if start_int < 0 or end_int <= start_int or end_int > len(text):
        return "", {"ok": False, "reason": "span_out_of_bounds"}
    quote = text[start_int:end_int].strip()
    if not quote:
        return "", {"ok": False, "reason": "empty_span_quote"}
    return quote, {"ok": True, "start": start_int, "end": end_int}


def _confidence_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get((value or "").lower(), 0)


def _candidate_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]
    return f"cand_{prefix}_{digest}"


def _coerce_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _entity_record_from_worker(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or item.get("label") or item.get("text") or "").strip()
    return {
        "entity_id": str(item.get("entity_id") or "").strip(),
        "name": name,
        "entity_type": str(item.get("entity_type") or item.get("type") or "person").strip() or "person",
        "aliases": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
    }


def worker_output_to_batch_candidates(
    source_id: str,
    page: int,
    worker_output: dict[str, Any],
    passage_packets: list[dict[str, Any]],
    provenance: dict[str, Any],
    *,
    analysis_mode: str = "relevant_evidence",
    max_quote_candidates: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    packets_by_id = {packet["passage_id"]: packet for packet in passage_packets}
    quote_candidates: list[dict[str, Any]] = []
    structured_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    quote_by_key: dict[tuple[str, int, int], str] = {}

    def ensure_quote_candidate(
        item: dict[str, Any],
        *,
        fallback_label: str = "",
        force_whole_passage: bool = False,
    ) -> str:
        passage_id = str(item.get("passage_id") or "").strip()
        packet = packets_by_id.get(passage_id)
        if not packet:
            skipped.append({"reason": "unknown_passage_id", "item": item})
            return ""
        if force_whole_passage or item.get("start") is None or item.get("end") is None:
            start = 0
            end = len(packet.get("text", ""))
            quote = packet.get("text", "").strip()
            span_status = {"ok": bool(quote), "start": start, "end": end}
            if not quote:
                span_status = {"ok": False, "reason": "empty_passage"}
        else:
            quote, span_status = quote_from_span(packet, item.get("start"), item.get("end"))
            start = span_status.get("start", item.get("start"))
            end = span_status.get("end", item.get("end"))
        if not span_status.get("ok"):
            skipped.append({"reason": span_status.get("reason", "invalid_quote_span"), "passage_id": passage_id})
            return ""
        key = (passage_id, int(start), int(end))
        if key in quote_by_key:
            return quote_by_key[key]
        confidence = str(item.get("confidence") or "medium").lower()
        candidate_id = _candidate_id("quote", source_id, page, passage_id, start, end, quote)
        candidate = {
            "candidate_id": candidate_id,
            "candidate_type": "quote",
            "kind": "quote",
            "source_id": source_id,
            "page": page,
            "label": quote,
            "quote": quote,
            "confidence": confidence if confidence in {"high", "medium", "low"} else "medium",
            "status": "candidate",
            "review_status": "candidate",
            "action": "Worker-AI passage; review this exact OCR quote before promoting",
            "provenance": {
                **provenance,
                "passage_id": passage_id,
                "span_start": start,
                "span_end": end,
                "worker_reconstructed_quote": True,
            },
            "score": item.get("score"),
            "candidate_reason": str(item.get("reason") or fallback_label or "worker suggested evidence"),
            "analysis_engine": "worker_ai",
            "worker_passage_id": passage_id,
        }
        article_context = packet.get("article_context") or {}
        if article_context:
            candidate["article_context"] = article_context
        quote_candidates.append(candidate)
        quote_by_key[key] = candidate_id
        return candidate_id

    quote_items = _coerce_list(worker_output.get("quote_candidates") or worker_output.get("quotes"))
    for item in quote_items:
        ensure_quote_candidate(item)

    def quote_candidate_for_structured_item(item: dict[str, Any]) -> str:
        passage_id = str(item.get("passage_id") or "").strip()
        for candidate in quote_candidates:
            if candidate.get("worker_passage_id") == passage_id:
                return candidate.get("candidate_id", "")
        return ensure_quote_candidate(item, fallback_label="parent quote for structured suggestion", force_whole_passage=True)

    def attach_structured_candidate(kind: str, item: dict[str, Any], quote_candidate_id: str, label: str) -> None:
        if not quote_candidate_id:
            return
        confidence = str(item.get("confidence") or "medium").lower()
        candidate = {
            "candidate_id": _candidate_id(kind, source_id, page, quote_candidate_id, label, json.dumps(item, ensure_ascii=False, sort_keys=True)),
            "candidate_type": kind,
            "kind": kind,
            "source_id": source_id,
            "page": page,
            "evidence_id": "",
            "quote_candidate_id": quote_candidate_id,
            "quote": "",
            "label": label,
            "confidence": confidence if confidence in {"high", "medium", "low"} else "medium",
            "status": "candidate",
            "review_status": "candidate",
            "source": "worker_ai",
            "analysis_engine": "worker_ai",
            "provenance": {
                **provenance,
                "passage_id": item.get("passage_id") or "",
                "span_start": item.get("start"),
                "span_end": item.get("end"),
            },
            "note": str(item.get("note") or item.get("reason") or ""),
        }
        if kind in {"entity", "place"}:
            entity = _entity_record_from_worker(item)
            if not entity["name"]:
                skipped.append({"reason": "missing_entity_name", "item": item})
                return
            candidate["entity"] = entity
            candidate["entity_id"] = entity.get("entity_id", "")
            candidate["entity_name"] = entity["name"]
            candidate["entity_type"] = entity["entity_type"]
            candidate["action"] = "Create/confirm worker-suggested place mention" if kind == "place" else "Create/confirm worker-suggested entity mention"
        elif kind == "keyword":
            keyword = str(item.get("keyword") or item.get("label") or label).strip()
            if not keyword:
                skipped.append({"reason": "missing_keyword", "item": item})
                return
            candidate["keyword"] = keyword
            candidate["action"] = "Approve worker-suggested keyword"
        elif kind == "relationship":
            relationship = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
            subject = _entity_record_from_worker(relationship.get("subject") if isinstance(relationship.get("subject"), dict) else {"name": relationship.get("subject_name")})
            object_record = _entity_record_from_worker(relationship.get("object") if isinstance(relationship.get("object"), dict) else {"name": relationship.get("object_name")})
            candidate["relationship"] = {
                "subject": subject,
                "object": object_record,
                "relation_type": str(relationship.get("relation_type") or "").strip(),
            }
            candidate["action"] = "Confirm worker-suggested relationship"
        elif kind == "attitude":
            attitude = item.get("attitude") if isinstance(item.get("attitude"), dict) else item
            speaker = _entity_record_from_worker(attitude.get("speaker") if isinstance(attitude.get("speaker"), dict) else {"name": attitude.get("speaker_name")})
            target = _entity_record_from_worker(attitude.get("target") if isinstance(attitude.get("target"), dict) else {"name": attitude.get("target_name")})
            candidate["attitude"] = {
                "speaker": speaker,
                "target": target,
                "attitude_type": str(attitude.get("attitude_type") or "").strip(),
                "polarity": str(attitude.get("polarity") or "").strip(),
            }
            candidate["action"] = "Confirm worker-suggested attitude"
        elif kind == "claim":
            candidate["claim"] = {"text": str(item.get("text") or item.get("claim") or label).strip()}
            candidate["action"] = "Review worker-suggested claim"
        elif kind == "note":
            candidate["note"] = str(item.get("note") or label).strip()
            candidate["action"] = "Create worker-suggested reading note"
        structured_candidates.append(candidate)

    structured_specs = [
        ("entity", worker_output.get("entity_candidates") or worker_output.get("entities")),
        ("relationship", worker_output.get("relationship_candidates") or worker_output.get("relationships")),
        ("attitude", worker_output.get("attitude_candidates") or worker_output.get("attitudes")),
        ("keyword", worker_output.get("keyword_candidates") or worker_output.get("keywords")),
        ("claim", worker_output.get("claim_candidates") or worker_output.get("claims")),
        ("note", worker_output.get("note_candidates") or worker_output.get("notes")),
    ]
    for kind, values in structured_specs:
        for item in _coerce_list(values):
            if kind == "entity":
                entity_type = str(item.get("entity_type") or item.get("type") or "person").strip()
                actual_kind = "place" if entity_type == "place" else "entity"
                label = str(item.get("name") or item.get("label") or item.get("text") or "").strip()
            elif kind == "keyword":
                actual_kind = "keyword"
                label = str(item.get("keyword") or item.get("label") or "").strip()
            elif kind == "claim":
                actual_kind = "claim"
                label = str(item.get("text") or item.get("claim") or item.get("label") or "").strip()
            elif kind == "note":
                actual_kind = "note"
                label = str(item.get("note") or item.get("label") or "").strip()
            else:
                actual_kind = kind
                label = str(item.get("label") or item.get("relation_type") or item.get("attitude_type") or kind).strip()
            quote_id = quote_candidate_for_structured_item(item)
            attach_structured_candidate(actual_kind, item, quote_id, label or actual_kind)

    quote_candidates.sort(key=lambda candidate: (_confidence_rank(candidate.get("confidence", "")), candidate.get("score") or 0), reverse=True)
    if analysis_mode != "wide_entities":
        keep_ids = {candidate["candidate_id"] for candidate in quote_candidates[:max_quote_candidates]}
        quote_candidates = quote_candidates[:max_quote_candidates]
        structured_candidates = [
            candidate for candidate in structured_candidates if candidate.get("quote_candidate_id") in keep_ids
        ]
    return quote_candidates, structured_candidates, skipped


class TextWorker:
    def __init__(
        self,
        *,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        config = worker_config_from_env()
        self.provider = provider or config.provider
        if self.provider == "poe":
            self.api_key = api_key or os.getenv("POE_API_KEY", "").strip()
            self.model = model or os.getenv("POE_WORKER_MODEL", "").strip() or os.getenv("KOSHU_WORKER_MODEL", "").strip()
            self.base_url = base_url or os.getenv("POE_BASE_URL", "https://api.poe.com/v1/chat/completions").strip()
        elif self.provider == "openrouter":
            self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip()
            self.model = model or os.getenv("OPENROUTER_WORKER_MODEL", "").strip() or os.getenv("KOSHU_WORKER_MODEL", "").strip()
            self.base_url = base_url or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions").strip()
        else:
            raise ValueError(f"Unsupported worker provider: {self.provider}")

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def call_json(self, *, system_prompt: str, user_payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError(f"{self.provider} worker API key and model are required for worker AI")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Koshu Research Workbench",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.provider == "poe":
            # Poe currently ignores response_format in Chat Completions, so the
            # skill prompt and parse fallback remain the JSON guarantee.
            payload.pop("response_format", None)
        retryable_errors = (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.TimeoutException,
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(self.base_url, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(f"{self.provider} worker error ({response.status_code}): {response.text}")
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise RuntimeError(f"{self.provider} worker error ({response.status_code}): {response.text}")
                data = response.json()
                break
            except retryable_errors as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise RuntimeError(f"{self.provider} worker request failed after 3 attempts: {exc!r}") from exc
        else:
            raise RuntimeError(f"{self.provider} worker request failed after 3 attempts: {last_error}")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected {self.provider} response shape: {data}") from exc
        return parse_worker_json(content)


class OpenRouterTextWorker(TextWorker):
    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        super().__init__(provider="openrouter", api_key=api_key, model=model, base_url=base_url)


class PoeTextWorker(TextWorker):
    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        super().__init__(provider="poe", api_key=api_key, model=model, base_url=base_url)


def build_worker_payload(
    *,
    source: dict[str, Any],
    page: int,
    passage_packets: list[dict[str, Any]],
    analysis_mode: str,
    source_skill: str = "",
) -> dict[str, Any]:
    return {
        "analysis_mode": analysis_mode,
        "source": {
            "source_id": source.get("source_id", ""),
            "title": source.get("title", ""),
            "title_original": source.get("title_original", ""),
            "citation": source.get("citation", ""),
            "date": source.get("date", ""),
            "document_type": source.get("document_type", ""),
        },
        "page": page,
        "source_specific_instructions": source_skill,
        "passages": passage_packets,
        "output_contract": {
            "quote_candidates": "Optional high-value evidence spans. Each item must include passage_id, start, end.",
            "entity_candidates": "Broad entity mentions. Each item must include passage_id and name; start/end are preferred.",
            "relationship_candidates": "Relationship hints. Each item must include passage_id plus subject/object names and relation_type when possible.",
            "attitude_candidates": "Attitude hints. Each item must include passage_id plus speaker/target names, attitude_type, and polarity when possible.",
            "no_rewritten_quotes": "Never copy or rewrite OCR quote text. Return passage_id and offsets only.",
        },
    }


async def analyze_page_with_worker(
    *,
    source: dict[str, Any],
    page: int,
    ocr_text: str,
    provenance: dict[str, Any],
    article_context: dict[str, Any] | None = None,
    analysis_mode: str = "relevant_evidence",
    skill_id: str = "relevant_passage_selection",
    source_skill_id: str | None = None,
    max_quote_candidates: int = 3,
    client: TextWorker | None = None,
) -> dict[str, Any]:
    passage_packets = build_passage_packets(
        source.get("source_id", ""),
        page,
        ocr_text,
        article_context=article_context,
    )
    if not passage_packets:
        return {
            "ok": False,
            "reason": "no_passages",
            "passages": [],
            "quote_candidates": [],
            "structured_candidates": [],
            "skipped": [],
        }
    worker = client or TextWorker()
    if not worker.available:
        return {
            "ok": False,
            "reason": "worker_not_configured",
            "passages": passage_packets,
            "quote_candidates": [],
            "structured_candidates": [],
            "skipped": [],
        }
    skill_doc = load_skill_doc(skill_id)
    source_skill = load_skill_doc(source_skill_id) if source_skill_id else ""
    payload = build_worker_payload(
        source=source,
        page=page,
        passage_packets=passage_packets,
        analysis_mode=analysis_mode,
        source_skill=source_skill,
    )
    worker_output = await worker.call_json(system_prompt=skill_doc, user_payload=payload)
    quote_candidates, structured_candidates, skipped = worker_output_to_batch_candidates(
        source.get("source_id", ""),
        page,
        worker_output,
        passage_packets,
        provenance,
        analysis_mode=analysis_mode,
        max_quote_candidates=max_quote_candidates,
    )
    return {
        "ok": True,
        "reason": "worker_ai_completed",
        "model": worker.model,
        "passages": passage_packets,
        "worker_output": worker_output,
        "quote_candidates": quote_candidates,
        "structured_candidates": structured_candidates,
        "skipped": skipped,
    }
