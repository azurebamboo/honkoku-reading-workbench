#!/usr/bin/env python3
"""Validate reviewed document-level extraction artifacts."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from typing import Any


import os

ROOT = Path(__file__).resolve().parents[1]

def get_project_id() -> str:
    return os.environ.get("KOSHU_PROJECT", "default")

def get_project_dir() -> Path:
    project_id = get_project_id()
    if project_id == "default":
        return ROOT
    else:
        return ROOT / "projects" / project_id

def get_extractions_dir() -> Path:
    return get_project_dir() / "artifacts" / "extractions"

def get_sources_path() -> Path:
    return get_project_dir() / "sources" / "metadata" / "sources.json"


def get_local_state_path() -> Path:
    return get_project_dir() / "sources" / "local_state.json"

REQUIRED_FIELDS = {
    "source_id": str,
    "collection": str,
    "citation": str,
    "title": str,
    "title_original": str,
    "date": str,
    "date_certainty": str,
    "language": list,
    "document_type": str,
    "external_reference": str,
    "summary_en": str,
    "notes": str,
    "entities": list,
    "claims": list,
    "keywords": list,
    "provenance": dict,
}

ALLOWED_STATUSES = {"draft", "reviewed", "needs_review", "needs_revision"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def source_records() -> dict[str, dict[str, Any]]:
    if not get_sources_path().exists():
        return {}
    return {
        record["source_id"]: record
        for record in load_json(get_sources_path())
        if isinstance(record, dict) and isinstance(record.get("source_id"), str)
    }


def local_state_entries() -> dict[str, dict[str, Any]]:
    if not get_local_state_path().exists():
        return {}
    state = load_json(get_local_state_path())
    entries = state.get("sources", {}) if isinstance(state, dict) else {}
    return entries if isinstance(entries, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_is_excluded(source_id: str) -> bool:
    return local_state_entries().get(source_id, {}).get("policy") == "excluded"


def source_resolution_error(source_id: str, artifact: dict[str, Any]) -> str | None:
    source = source_records().get(source_id, {})
    checksum = source.get("checksum_sha256") or artifact.get("source_checksum_sha256")
    if not isinstance(checksum, str) or not checksum:
        return "shared source checksum is required for reviewed evidence"

    entry = local_state_entries().get(source_id, {})
    bound_path = entry.get("local_pdf_path")
    if isinstance(bound_path, str) and bound_path:
        path = Path(bound_path).expanduser()
        if not path.is_absolute():
            path = get_project_dir() / path
        if path.is_file():
            actual = sha256_file(path)
            if actual == checksum and entry.get("checksum_sha256") == checksum:
                return None
            return "local PDF binding checksum does not match the shared source checksum"

    legacy = source.get("local_pdf")
    if isinstance(legacy, str) and legacy:
        legacy_path = Path(legacy)
        if legacy_path.parts[:2] != ("sources", "raw"):
            legacy_path = Path("sources") / "raw" / legacy_path
        path = get_project_dir() / legacy_path
        if path.is_file() and sha256_file(path) == checksum:
            return None

    stable_reference = any(
        isinstance(source.get(field), str) and source.get(field, "").strip()
        for field in ("external_reference", "call_number", "citation")
    )
    if entry.get("policy") == "catalog_only" and stable_reference:
        return None
    return "reviewed evidence requires a checksum-matched local PDF or confirmed catalog-only provenance"


def require_string(
    path: Path, errors: list[str], record: dict[str, Any], field: str, label: str
) -> None:
    if not isinstance(record.get(field), str) or not record.get(field):
        errors.append(f"{path}: {label}.{field} is required")


def require_unique_ids(
    path: Path, errors: list[str], records: list[Any], id_field: str, label: str
) -> set[str]:
    ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"{path}: {label}[{index}] must be an object")
            continue
        record_id = record.get(id_field)
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{path}: {label}[{index}].{id_field} is required")
            continue
        if record_id in ids:
            errors.append(f"{path}: duplicate {label}.{id_field} `{record_id}`")
        ids.add(record_id)
    return ids


def validate_evidence_graph(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    if data.get("extraction_schema_version") != "evidence-graph-v1":
        return

    scope = data.get("extraction_scope")
    if not isinstance(scope, dict):
        errors.append(f"{path}: extraction_scope is required for evidence-graph-v1")
        return

    page_start = scope.get("page_start")
    page_end = scope.get("page_end")
    if not isinstance(page_start, int) or not isinstance(page_end, int):
        errors.append(f"{path}: extraction_scope page_start/page_end must be integers")
        return
    if page_start > page_end:
        errors.append(f"{path}: extraction_scope.page_start cannot exceed page_end")

    evidence_quotes = data.get("evidence_quotes", [])
    entity_records = data.get("entity_records", [])
    entity_mentions = data.get("entity_mentions", [])
    relationship_claims = data.get("relationship_claims", [])
    attitude_claims = data.get("attitude_claims", [])
    timeline_events = data.get("timeline_events", [])
    timeline_event_links = data.get("timeline_event_links", [])

    for field, records in (
        ("evidence_quotes", evidence_quotes),
        ("entity_records", entity_records),
        ("entity_mentions", entity_mentions),
        ("relationship_claims", relationship_claims),
        ("attitude_claims", attitude_claims),
        ("timeline_events", timeline_events),
        ("timeline_event_links", timeline_event_links),
    ):
        if not isinstance(records, list):
            errors.append(f"{path}: {field} must be a list")
            return

    evidence_ids = require_unique_ids(
        path, errors, evidence_quotes, "evidence_id", "evidence_quotes"
    )
    entity_ids = require_unique_ids(
        path, errors, entity_records, "entity_id", "entity_records"
    )
    require_unique_ids(path, errors, entity_mentions, "mention_id", "entity_mentions")
    require_unique_ids(
        path, errors, relationship_claims, "relationship_id", "relationship_claims"
    )
    require_unique_ids(path, errors, attitude_claims, "attitude_id", "attitude_claims")
    event_ids = require_unique_ids(path, errors, timeline_events, "event_id", "timeline_events")
    require_unique_ids(path, errors, timeline_event_links, "link_id", "timeline_event_links")

    source_id = data.get("source_id")
    reviewed = data.get("provenance", {}).get("status") == "reviewed"
    if reviewed and isinstance(source_id, str):
        source = source_records().get(source_id, {})
        artifact_checksum = data.get("source_checksum_sha256")
        if artifact_checksum and artifact_checksum != source.get("checksum_sha256"):
            errors.append(f"{path}: source_checksum_sha256 does not match the shared source record")
        resolution_error = source_resolution_error(source_id, data)
        if resolution_error:
            errors.append(f"{path}: source resolution failed: {resolution_error}")
    for index, evidence in enumerate(evidence_quotes):
        if not isinstance(evidence, dict):
            continue
        label = f"evidence_quotes[{index}]"
        for field in ("source_id", "quote", "ocr_page_json"):
            require_string(path, errors, evidence, field, label)
        if evidence.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        for field in ("ocr_page_json",):
            value = evidence.get(field)
            if reviewed and isinstance(value, str) and value and not path_exists(value):
                errors.append(f"{path}: {label}.{field} does not exist: {value}")
        if reviewed:
            reviewed_ocr = evidence.get("corrected_ocr_page_json") or evidence.get("ocr_page_json")
            if not isinstance(reviewed_ocr, str) or "/corrected/" not in f"/{reviewed_ocr}":
                errors.append(f"{path}: {label} must reference reviewed corrected OCR")
            evidence_checksum = evidence.get("source_checksum_sha256")
            if evidence_checksum and evidence_checksum != data.get("source_checksum_sha256"):
                errors.append(f"{path}: {label}.source_checksum_sha256 must match the artifact")
        page = evidence.get("page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.page must be an integer")
        elif page < page_start or page > page_end:
            errors.append(
                f"{path}: {label}.page {page} outside scope {page_start}-{page_end}"
            )

    for index, entity in enumerate(entity_records):
        if not isinstance(entity, dict):
            continue
        label = f"entity_records[{index}]"
        for field in ("canonical_name", "entity_type"):
            require_string(path, errors, entity, field, label)
        if not isinstance(entity.get("aliases", []), list):
            errors.append(f"{path}: {label}.aliases must be a list")

    for index, mention in enumerate(entity_mentions):
        if not isinstance(mention, dict):
            continue
        label = f"entity_mentions[{index}]"
        for field in ("entity_id", "source_id", "name_as_appears", "evidence_id"):
            require_string(path, errors, mention, field, label)
        if mention.get("entity_id") not in entity_ids:
            errors.append(f"{path}: {label}.entity_id does not resolve")
        if mention.get("evidence_id") not in evidence_ids:
            errors.append(f"{path}: {label}.evidence_id does not resolve")
        if mention.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        page = mention.get("page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.page must be an integer")
        elif page < page_start or page > page_end:
            errors.append(
                f"{path}: {label}.page {page} outside scope {page_start}-{page_end}"
            )

    for index, claim in enumerate(relationship_claims):
        if not isinstance(claim, dict):
            continue
        label = f"relationship_claims[{index}]"
        for field in (
            "subject_entity_id",
            "object_entity_id",
            "relation_type",
            "source_id",
            "evidence_id",
            "quote",
        ):
            require_string(path, errors, claim, field, label)
        for field in ("subject_entity_id", "object_entity_id"):
            if claim.get(field) not in entity_ids:
                errors.append(f"{path}: {label}.{field} does not resolve")
        if claim.get("evidence_id") not in evidence_ids:
            errors.append(f"{path}: {label}.evidence_id does not resolve")
        if claim.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        page = claim.get("page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.page must be an integer")
        elif page < page_start or page > page_end:
            errors.append(
                f"{path}: {label}.page {page} outside scope {page_start}-{page_end}"
            )

    for index, claim in enumerate(attitude_claims):
        if not isinstance(claim, dict):
            continue
        label = f"attitude_claims[{index}]"
        for field in (
            "speaker_entity_id",
            "target_entity_id",
            "attitude_type",
            "polarity",
            "source_id",
            "evidence_id",
            "quote",
        ):
            require_string(path, errors, claim, field, label)
        for field in ("speaker_entity_id", "target_entity_id"):
            if claim.get(field) not in entity_ids:
                errors.append(f"{path}: {label}.{field} does not resolve")
        if claim.get("evidence_id") not in evidence_ids:
            errors.append(f"{path}: {label}.evidence_id does not resolve")
        if claim.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        page = claim.get("page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.page must be an integer")
        elif page < page_start or page > page_end:
            errors.append(
                f"{path}: {label}.page {page} outside scope {page_start}-{page_end}"
            )

    for index, event in enumerate(timeline_events):
        if not isinstance(event, dict):
            continue
        label = f"timeline_events[{index}]"
        for field in ("source_id", "evidence_id", "summary", "event_type"):
            require_string(path, errors, event, field, label)
        if event.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        if event.get("evidence_id") not in evidence_ids:
            errors.append(f"{path}: {label}.evidence_id does not resolve")
        page = event.get("page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.page must be an integer")
        elif page < page_start or page > page_end:
            errors.append(
                f"{path}: {label}.page {page} outside scope {page_start}-{page_end}"
            )
        date_certainty = event.get("date_certainty", "")
        if date_certainty and date_certainty not in {"exact", "approximate", "inferred", "unknown"}:
            errors.append(f"{path}: {label}.date_certainty must be exact, approximate, inferred, or unknown")
        confidence = event.get("confidence", "")
        if confidence and confidence not in {"high", "medium", "low"}:
            errors.append(f"{path}: {label}.confidence must be high, medium, or low")
        traits = event.get("traits", [])
        if not isinstance(traits, list):
            errors.append(f"{path}: {label}.traits must be a list")
        require_review_fields(path, errors, event, label)

    for index, link in enumerate(timeline_event_links):
        if not isinstance(link, dict):
            continue
        label = f"timeline_event_links[{index}]"
        for field in ("event_id", "entity_id", "entity_name", "entity_type", "role"):
            require_string(path, errors, link, field, label)
        if link.get("event_id") not in event_ids:
            errors.append(f"{path}: {label}.event_id does not resolve")
        if link.get("entity_id") not in entity_ids:
            errors.append(f"{path}: {label}.entity_id does not resolve")


def resolve_validation_path(value: str) -> Path:
    path_obj = Path(value)
    if path_obj.is_absolute():
        return path_obj
    
    parts = path_obj.parts
    if len(parts) > 2 and parts[0] == "projects":
        exact_path = ROOT / path_obj
        if exact_path.exists():
            return exact_path
        sub_path = Path(*parts[2:])
        proj_path = get_project_dir() / sub_path
        if proj_path.exists():
            return proj_path
            
    proj_path = get_project_dir() / path_obj
    if proj_path.exists():
        return proj_path
    return ROOT / path_obj


def path_exists(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return resolve_validation_path(value).exists()


def require_review_fields(
    path: Path, errors: list[str], record: dict[str, Any], label: str
) -> None:
    status = record.get("review_status")
    if status not in ALLOWED_STATUSES:
        errors.append(f"{path}: {label}.review_status must be one of {sorted(ALLOWED_STATUSES)}")
        return
    if status == "reviewed":
        for field in ("reviewer", "reviewed_at"):
            require_string(path, errors, record, field, label)


def validate_officer_tables(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    tables = data.get("organization_officer_tables", [])
    terms = data.get("organization_officer_terms", [])
    if not tables and not terms:
        return
    if not isinstance(tables, list):
        errors.append(f"{path}: organization_officer_tables must be a list")
        return
    if not isinstance(terms, list):
        errors.append(f"{path}: organization_officer_terms must be a list")
        return

    source_id = data.get("source_id")
    table_ids = require_unique_ids(
        path, errors, tables, "table_id", "organization_officer_tables"
    )
    require_unique_ids(path, errors, terms, "term_id", "organization_officer_terms")

    table_pages: dict[str, int] = {}
    for index, table in enumerate(tables):
        if not isinstance(table, dict):
            continue
        label = f"organization_officer_tables[{index}]"
        for field in (
            "source_id",
            "table_title",
            "organization_name_original",
        ):
            require_string(path, errors, table, field, label)
        if table.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        page = table.get("pdf_page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.pdf_page must be an integer")
        else:
            table_pages[table["table_id"]] = page
        if not isinstance(table.get("crop_region", {}), dict):
            errors.append(f"{path}: {label}.crop_region must be an object")
        if table.get("review_status") == "reviewed" and table.get("source_pdf") and not path_exists(table.get("source_pdf")):
            errors.append(f"{path}: {label}.source_pdf does not exist: {table.get('source_pdf')}")
        ocr_path = table.get("ocr_page_json")
        if table.get("review_status") == "reviewed" and isinstance(ocr_path, str) and ocr_path and not path_exists(ocr_path):
            errors.append(f"{path}: {label}.ocr_page_json does not exist: {ocr_path}")
        require_review_fields(path, errors, table, label)

    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            errors.append(f"{path}: organization_officer_terms[{index}] must be an object")
            continue
        label = f"organization_officer_terms[{index}]"
        for field in (
            "table_id",
            "source_id",
            "person_name_original",
            "organization_name_original",
            "role_original",
            "role_normalized",
            "evidence_quote",
            "confidence",
        ):
            require_string(path, errors, term, field, label)
        if term.get("table_id") not in table_ids:
            errors.append(f"{path}: {label}.table_id does not resolve")
        if term.get("source_id") != source_id:
            errors.append(f"{path}: {label}.source_id must match artifact source_id")
        page = term.get("pdf_page")
        if not isinstance(page, int):
            errors.append(f"{path}: {label}.pdf_page must be an integer")
        elif term.get("table_id") in table_pages and page != table_pages[term["table_id"]]:
            errors.append(f"{path}: {label}.pdf_page must match its table pdf_page")
        if not isinstance(term.get("overlap_organizations", []), list):
            errors.append(f"{path}: {label}.overlap_organizations must be a list")
        require_review_fields(path, errors, term, label)


def validate_artifact(path: Path) -> list[str]:
    errors: list[str] = []

    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return [f"{path}: top-level JSON value must be an object"]
    if isinstance(data.get("source_id"), str) and source_is_excluded(data["source_id"]):
        return []

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"{path}: missing required field `{field}`")
            continue
        if not isinstance(data[field], expected_type):
            errors.append(
                f"{path}: `{field}` must be {expected_type.__name__}, got {type(data[field]).__name__}"
            )

    source_id = data.get("source_id")
    artifact_id = data.get("artifact_id")
    if (
        isinstance(source_id, str)
        and path.stem != source_id
        and artifact_id != path.stem
    ):
        errors.append(
            f"{path}: filename stem should match source_id `{source_id}` or artifact_id `{path.stem}`"
        )

    provenance = data.get("provenance")
    if isinstance(provenance, dict):
        status = provenance.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"{path}: provenance.status must be one of {sorted(ALLOWED_STATUSES)}"
            )
        for field in ("reviewer", "extraction_date", "method"):
            if not isinstance(provenance.get(field), str) or not provenance.get(field):
                errors.append(f"{path}: provenance.{field} is required")

    for index, entity in enumerate(data.get("entities", [])):
        if not isinstance(entity, dict):
            errors.append(f"{path}: entities[{index}] must be an object")
            continue
        for field in ("name", "type"):
            if not isinstance(entity.get(field), str) or not entity.get(field):
                errors.append(f"{path}: entities[{index}].{field} is required")

    for index, claim in enumerate(data.get("claims", [])):
        if not isinstance(claim, dict):
            errors.append(f"{path}: claims[{index}] must be an object")
            continue
        if not isinstance(claim.get("text"), str) or not claim.get("text"):
            errors.append(f"{path}: claims[{index}].text is required")

    validate_evidence_graph(path, data, errors)
    validate_officer_tables(path, data, errors)

    return errors


def main() -> int:
    paths = [
        path
        for path in sorted(get_extractions_dir().glob("*.json"))
        if not source_is_excluded(path.stem)
    ]
    if not paths:
        print(f"No extraction artifacts found in {get_extractions_dir()}")
        return 1

    errors: list[str] = []
    for path in paths:
        errors.extend(validate_artifact(path))

    if errors:
        print("Extraction validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Validated {len(paths)} extraction artifact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
