#!/usr/bin/env python3
"""Build the generated SQLite database from tracked metadata and JSON artifacts."""

from __future__ import annotations

import json
import sqlite3
import csv
import hashlib
from pathlib import Path
import os
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_PROJECT_ID = os.environ.get("KOSHU_PROJECT", "default")

def get_project_dir() -> Path:
    if ACTIVE_PROJECT_ID == "default":
        return ROOT
    else:
        return ROOT / "projects" / ACTIVE_PROJECT_ID

DB_PATH = get_project_dir() / "db" / "koshu.sqlite"
SOURCES_PATH = get_project_dir() / "sources" / "metadata" / "sources.json"
EXTRACTIONS_DIR = get_project_dir() / "artifacts" / "extractions"
SHAREHOLDER_REVIEW_ROOT = get_project_dir() / "artifacts" / "shareholders" / "review"
LOCAL_STATE_PATH = get_project_dir() / "sources" / "local_state.json"

OFFICER_ROLE_RELATION_TYPES = {
    "會長": "chair_of",
    "会長": "chair_of",
    "會": "chair_of",
    "会": "chair_of",
    "專務": "managing_director_of",
    "専務": "managing_director_of",
    "專": "managing_director_of",
    "専": "managing_director_of",
    "取締": "director_of",
    "取": "director_of",
    "監察": "auditor_of",
    "監査": "auditor_of",
    "監": "auditor_of",
    "頭": "president_of",
}


def local_source_entries() -> dict[str, dict[str, Any]]:
    if not LOCAL_STATE_PATH.exists():
        return {}
    state = load_json(LOCAL_STATE_PATH)
    entries = state.get("sources", {}) if isinstance(state, dict) else {}
    return entries if isinstance(entries, dict) else {}


def source_is_excluded(source_id: str) -> bool:
    return local_source_entries().get(source_id, {}).get("policy") == "excluded"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_is_resolved(source: dict[str, Any]) -> bool:
    entry = local_source_entries().get(source["source_id"], {})
    if entry.get("policy") == "excluded":
        return False
    binding = entry.get("local_pdf_path")
    if isinstance(binding, str) and binding:
        path = Path(binding).expanduser()
        if not path.is_absolute():
            path = get_project_dir() / path
        if (
            path.is_file()
            and entry.get("checksum_sha256") == source.get("checksum_sha256")
            and sha256_file(path) == source.get("checksum_sha256")
        ):
            return True
    legacy = source.get("local_pdf")
    if isinstance(legacy, str) and legacy:
        legacy_path = Path(legacy)
        if legacy_path.parts[:2] != ("sources", "raw"):
            legacy_path = Path("sources") / "raw" / legacy_path
        full_path = get_project_dir() / legacy_path
        if full_path.is_file() and sha256_file(full_path) == source.get("checksum_sha256"):
            return True
    has_reference = any(
        isinstance(source.get(field), str) and source.get(field, "").strip()
        for field in ("external_reference", "call_number", "citation")
    )
    return entry.get("policy") == "catalog_only" and has_reference

OVERLAP_ROLE_SUFFIXES = (
    ("專務", "managing_director_of"),
    ("専務", "managing_director_of"),
    ("取締", "director_of"),
    ("監察", "auditor_of"),
    ("監査", "auditor_of"),
    ("會長", "chair_of"),
    ("会長", "chair_of"),
    ("專", "managing_director_of"),
    ("専", "managing_director_of"),
    ("取", "director_of"),
    ("監", "auditor_of"),
    ("會", "chair_of"),
    ("会", "chair_of"),
    ("頭", "president_of"),
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def stable_hash(*values: Any, length: int = 12) -> str:
    joined = "|".join("" if value is None else str(value) for value in values)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE sources (
            source_id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            repository TEXT,
            call_number TEXT,
            citation TEXT NOT NULL,
            title TEXT NOT NULL,
            title_original TEXT,
            date TEXT,
            date_certainty TEXT,
            language_json TEXT NOT NULL,
            document_type TEXT,
            local_pdf TEXT,
            checksum_sha256 TEXT,
            external_reference TEXT,
            rights_notes TEXT
        );

        CREATE TABLE documents (
            source_id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            citation TEXT NOT NULL,
            title TEXT NOT NULL,
            title_original TEXT,
            date TEXT,
            date_certainty TEXT,
            language_json TEXT NOT NULL,
            document_type TEXT,
            local_pdf TEXT,
            external_reference TEXT,
            summary_en TEXT,
            notes TEXT,
            provenance_json TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            name TEXT NOT NULL,
            name_original TEXT,
            romanization TEXT,
            type TEXT NOT NULL,
            role TEXT,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES documents(source_id)
        );

        CREATE TABLE claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            text TEXT NOT NULL,
            evidence TEXT,
            page INTEGER,
            confidence TEXT,
            FOREIGN KEY (source_id) REFERENCES documents(source_id)
        );

        CREATE TABLE keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            keyword TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES documents(source_id)
        );

        CREATE TABLE evidence_entities (
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            name_original TEXT,
            entity_type TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE evidence_quotes (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            quote TEXT NOT NULL,
            ocr_page_json TEXT NOT NULL,
            source_pdf TEXT NOT NULL,
            note TEXT,
            extraction_status TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE evidence_mentions (
            mention_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            name_as_appears TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            confidence TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY (entity_id) REFERENCES evidence_entities(entity_id),
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence_quotes(evidence_id)
        );

        CREATE TABLE relationship_claims (
            relationship_id TEXT PRIMARY KEY,
            subject_entity_id TEXT NOT NULL,
            object_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            evidence_id TEXT NOT NULL,
            quote TEXT NOT NULL,
            confidence TEXT NOT NULL,
            note TEXT,
            extraction_status TEXT NOT NULL,
            FOREIGN KEY (subject_entity_id) REFERENCES evidence_entities(entity_id),
            FOREIGN KEY (object_entity_id) REFERENCES evidence_entities(entity_id),
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence_quotes(evidence_id)
        );

        CREATE TABLE attitude_claims (
            attitude_id TEXT PRIMARY KEY,
            speaker_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            attitude_type TEXT NOT NULL,
            polarity TEXT NOT NULL,
            source_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            evidence_id TEXT NOT NULL,
            quote TEXT NOT NULL,
            confidence TEXT NOT NULL,
            note TEXT,
            extraction_status TEXT NOT NULL,
            FOREIGN KEY (speaker_entity_id) REFERENCES evidence_entities(entity_id),
            FOREIGN KEY (target_entity_id) REFERENCES evidence_entities(entity_id),
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence_quotes(evidence_id)
        );

        CREATE TABLE shareholder_tables (
            table_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            pdf_page INTEGER NOT NULL,
            printed_page TEXT,
            table_title TEXT NOT NULL,
            company_or_subject_original TEXT NOT NULL,
            data_date TEXT,
            ocr_page_json TEXT NOT NULL,
            source_pdf TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE shareholder_rows (
            row_id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            pdf_page INTEGER NOT NULL,
            printed_page TEXT,
            table_title TEXT,
            company_or_subject_original TEXT,
            data_date TEXT,
            rank INTEGER,
            shareholder_name_original TEXT NOT NULL,
            shareholder_name_normalized TEXT,
            shareholder_entity_id TEXT,
            location_original TEXT,
            shares INTEGER,
            share_unit TEXT,
            amount_yen REAL,
            ownership_percent REAL,
            ocr_quote TEXT NOT NULL,
            ocr_page_json TEXT NOT NULL,
            source_pdf TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (table_id) REFERENCES shareholder_tables(table_id),
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE organization_officer_tables (
            table_id TEXT PRIMARY KEY,
            artifact_id TEXT,
            source_id TEXT NOT NULL,
            pdf_page INTEGER NOT NULL,
            printed_page TEXT,
            table_title TEXT NOT NULL,
            organization_name_original TEXT NOT NULL,
            organization_entity_id TEXT,
            source_pdf TEXT NOT NULL,
            page_image TEXT,
            crop_image TEXT,
            crop_region_json TEXT NOT NULL,
            ocr_page_json TEXT,
            parse_artifact_path TEXT,
            parsing_engine TEXT,
            review_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE organization_officer_terms (
            term_id TEXT PRIMARY KEY,
            table_id TEXT NOT NULL,
            artifact_id TEXT,
            source_id TEXT NOT NULL,
            pdf_page INTEGER NOT NULL,
            printed_page TEXT,
            person_name_original TEXT NOT NULL,
            person_name_normalized TEXT,
            person_entity_id TEXT,
            organization_name_original TEXT NOT NULL,
            organization_entity_id TEXT,
            role_original TEXT NOT NULL,
            role_normalized TEXT NOT NULL,
            date_start TEXT,
            date_end TEXT,
            era_start TEXT,
            era_end TEXT,
            status_original TEXT,
            overlap_text TEXT,
            overlap_organizations_json TEXT NOT NULL,
            evidence_quote TEXT NOT NULL,
            crop_region_id TEXT,
            confidence TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (table_id) REFERENCES organization_officer_tables(table_id),
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        );

        CREATE TABLE timeline_events (
            event_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            evidence_id TEXT NOT NULL,
            event_date TEXT,
            date_label TEXT,
            date_certainty TEXT NOT NULL,
            date_basis TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence TEXT NOT NULL,
            traits_json TEXT NOT NULL,
            review_status TEXT NOT NULL,
            reviewer TEXT,
            reviewed_at TEXT,
            note TEXT,
            quote TEXT NOT NULL,
            ocr_page_json TEXT NOT NULL,
            source_pdf TEXT,
            extraction_status TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (evidence_id) REFERENCES evidence_quotes(evidence_id)
        );

        CREATE TABLE timeline_event_links (
            link_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            role TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES timeline_events(event_id),
            FOREIGN KEY (entity_id) REFERENCES evidence_entities(entity_id)
        );

        CREATE INDEX idx_documents_title ON documents(title);
        CREATE INDEX idx_entities_name ON entities(name);
        CREATE INDEX idx_keywords_keyword ON keywords(keyword);
        CREATE INDEX idx_evidence_entities_type_name
            ON evidence_entities(entity_type, canonical_name);
        CREATE INDEX idx_evidence_quotes_source_page
            ON evidence_quotes(source_id, page);
        CREATE INDEX idx_evidence_mentions_entity
            ON evidence_mentions(entity_id);
        CREATE INDEX idx_relationship_claims_type
            ON relationship_claims(relation_type);
        CREATE INDEX idx_relationship_claims_source_page
            ON relationship_claims(source_id, page);
        CREATE INDEX idx_attitude_claims_type_polarity
            ON attitude_claims(attitude_type, polarity);
        CREATE INDEX idx_attitude_claims_source_page
            ON attitude_claims(source_id, page);
        CREATE INDEX idx_shareholder_tables_source_page
            ON shareholder_tables(source_id, pdf_page);
        CREATE INDEX idx_shareholder_rows_name
            ON shareholder_rows(shareholder_name_original, shareholder_name_normalized);
        CREATE INDEX idx_shareholder_rows_source_page
            ON shareholder_rows(source_id, pdf_page);
        CREATE INDEX idx_shareholder_rows_subject
            ON shareholder_rows(company_or_subject_original);
        CREATE INDEX idx_officer_tables_source_page
            ON organization_officer_tables(source_id, pdf_page);
        CREATE INDEX idx_officer_tables_organization
            ON organization_officer_tables(organization_name_original);
        CREATE INDEX idx_officer_terms_person
            ON organization_officer_terms(person_name_original, person_name_normalized);
        CREATE INDEX idx_officer_terms_organization
            ON organization_officer_terms(organization_name_original);
        CREATE INDEX idx_officer_terms_role
            ON organization_officer_terms(role_normalized);
        CREATE INDEX idx_officer_terms_source_page
            ON organization_officer_terms(source_id, pdf_page);
        CREATE INDEX idx_timeline_events_source_page
            ON timeline_events(source_id, page);
        CREATE INDEX idx_timeline_events_date
            ON timeline_events(event_date, date_label);
        CREATE INDEX idx_timeline_events_type
            ON timeline_events(event_type);
        CREATE INDEX idx_timeline_events_review_status
            ON timeline_events(review_status);
        CREATE INDEX idx_timeline_event_links_entity
            ON timeline_event_links(entity_id);
        """
    )


def insert_sources(connection: sqlite3.Connection) -> set[str]:
    sources = load_json(SOURCES_PATH)
    source_ids: set[str] = set()
    for source in sources:
        if source_is_excluded(source["source_id"]):
            continue
        source_ids.add(source["source_id"])
        connection.execute(
            """
            INSERT INTO sources (
                source_id, collection, repository, call_number, citation, title,
                title_original, date, date_certainty, language_json, document_type,
                local_pdf, checksum_sha256, external_reference, rights_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["source_id"],
                source["collection"],
                source.get("repository", ""),
                source.get("call_number", ""),
                source["citation"],
                source["title"],
                source.get("title_original", ""),
                source.get("date", ""),
                source.get("date_certainty", ""),
                json.dumps(source.get("language", []), ensure_ascii=False),
                source.get("document_type", ""),
                source.get("local_pdf", ""),
                source.get("checksum_sha256", ""),
                source.get("external_reference", ""),
                source.get("rights_notes", ""),
            ),
        )
    return source_ids


def insert_source_from_extraction(
    connection: sqlite3.Connection, extraction: dict[str, Any], source_ids: set[str]
) -> None:
    source_id = extraction["source_id"]
    if source_id in source_ids:
        return
    connection.execute(
        """
        INSERT INTO sources (
            source_id, collection, repository, call_number, citation, title,
            title_original, date, date_certainty, language_json, document_type,
            local_pdf, checksum_sha256, external_reference, rights_notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            extraction["collection"],
            "",
            "",
            extraction["citation"],
            extraction["title"],
            extraction.get("title_original", ""),
            extraction.get("date", ""),
            extraction.get("date_certainty", ""),
            json.dumps(extraction.get("language", []), ensure_ascii=False),
            extraction.get("document_type", ""),
            extraction.get("local_pdf", ""),
            "",
            extraction.get("external_reference", ""),
            "Inserted from reviewed extraction fixture because source metadata was absent.",
        ),
    )
    source_ids.add(source_id)


def insert_extraction(connection: sqlite3.Connection, extraction: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO documents (
            source_id, collection, citation, title, title_original, date,
            date_certainty, language_json, document_type, local_pdf,
            external_reference, summary_en, notes, provenance_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            extraction["source_id"],
            extraction["collection"],
            extraction["citation"],
            extraction["title"],
            extraction["title_original"],
            extraction["date"],
            extraction["date_certainty"],
            json.dumps(extraction["language"], ensure_ascii=False),
            extraction["document_type"],
            extraction.get("local_pdf", ""),
            extraction["external_reference"],
            extraction["summary_en"],
            extraction["notes"],
            json.dumps(extraction["provenance"], ensure_ascii=False),
        ),
    )

    for entity in extraction["entities"]:
        connection.execute(
            """
            INSERT INTO entities (
                source_id, name, name_original, romanization, type, role, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction["source_id"],
                entity["name"],
                entity.get("name_original", ""),
                entity.get("romanization", ""),
                entity["type"],
                entity.get("role", ""),
                entity.get("notes", ""),
            ),
        )

    for claim in extraction["claims"]:
        connection.execute(
            """
            INSERT INTO claims (source_id, text, evidence, page, confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                extraction["source_id"],
                claim["text"],
                claim.get("evidence", ""),
                claim.get("page"),
                claim.get("confidence", ""),
            ),
        )

    for keyword in extraction["keywords"]:
        connection.execute(
            "INSERT INTO keywords (source_id, keyword) VALUES (?, ?)",
            (extraction["source_id"], keyword),
        )


def insert_evidence_extraction(
    connection: sqlite3.Connection, extraction: dict[str, Any]
) -> None:
    status = extraction.get("provenance", {}).get("status", "draft")

    for entity in extraction.get("entity_records", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO evidence_entities (
                entity_id, canonical_name, name_original, entity_type, aliases_json, notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entity["entity_id"],
                entity["canonical_name"],
                entity.get("name_original", ""),
                entity["entity_type"],
                json.dumps(entity.get("aliases", []), ensure_ascii=False),
                entity.get("notes", ""),
            ),
        )

    for evidence in extraction.get("evidence_quotes", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO evidence_quotes (
                evidence_id, source_id, page, quote, ocr_page_json, source_pdf,
                note, extraction_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence["evidence_id"],
                evidence["source_id"],
                evidence["page"],
                evidence["quote"],
                evidence["ocr_page_json"],
                evidence.get("source_pdf", ""),
                evidence.get("note", ""),
                status,
            ),
        )

    for mention in extraction.get("entity_mentions", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO evidence_mentions (
                mention_id, entity_id, source_id, page, name_as_appears,
                evidence_id, confidence, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mention["mention_id"],
                mention["entity_id"],
                mention["source_id"],
                mention["page"],
                mention["name_as_appears"],
                mention["evidence_id"],
                mention.get("confidence", ""),
                mention.get("note", ""),
            ),
        )

    for claim in extraction.get("relationship_claims", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO relationship_claims (
                relationship_id, subject_entity_id, object_entity_id, relation_type,
                source_id, page, evidence_id, quote, confidence, note, extraction_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim["relationship_id"],
                claim["subject_entity_id"],
                claim["object_entity_id"],
                claim["relation_type"],
                claim["source_id"],
                claim["page"],
                claim["evidence_id"],
                claim["quote"],
                claim.get("confidence", ""),
                claim.get("note", ""),
                status,
            ),
        )

    for claim in extraction.get("attitude_claims", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO attitude_claims (
                attitude_id, speaker_entity_id, target_entity_id, attitude_type,
                polarity, source_id, page, evidence_id, quote, confidence, note,
                extraction_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim["attitude_id"],
                claim["speaker_entity_id"],
                claim["target_entity_id"],
                claim["attitude_type"],
                claim["polarity"],
                claim["source_id"],
                claim["page"],
                claim["evidence_id"],
                claim["quote"],
                claim.get("confidence", ""),
                claim.get("note", ""),
                status,
            ),
        )

    quotes_by_id = {
        evidence["evidence_id"]: evidence
        for evidence in extraction.get("evidence_quotes", [])
        if isinstance(evidence, dict) and evidence.get("evidence_id")
    }
    reviewed_event_ids: set[str] = set()
    for event in extraction.get("timeline_events", []):
        if not isinstance(event, dict):
            continue
        if event.get("review_status") != "reviewed":
            continue
        evidence = quotes_by_id.get(event.get("evidence_id"))
        if not evidence:
            continue
        event_id = event["event_id"]
        reviewed_event_ids.add(event_id)
        connection.execute(
            """
            INSERT OR REPLACE INTO timeline_events (
                event_id, source_id, page, evidence_id, event_date, date_label,
                date_certainty, date_basis, event_type, summary, confidence,
                traits_json, review_status, reviewer, reviewed_at, note, quote,
                ocr_page_json, source_pdf, extraction_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event["source_id"],
                event["page"],
                event["evidence_id"],
                event.get("event_date", ""),
                event.get("date_label", ""),
                event.get("date_certainty", "unknown") or "unknown",
                event.get("date_basis", "event_date") or "event_date",
                event["event_type"],
                event["summary"],
                event.get("confidence", "medium") or "medium",
                json.dumps(event.get("traits", []), ensure_ascii=False),
                event["review_status"],
                event.get("reviewer", ""),
                event.get("reviewed_at", ""),
                event.get("note", ""),
                evidence["quote"],
                evidence["ocr_page_json"],
                evidence.get("source_pdf", ""),
                status,
            ),
        )

    for link in extraction.get("timeline_event_links", []):
        if not isinstance(link, dict):
            continue
        if link.get("event_id") not in reviewed_event_ids:
            continue
        connection.execute(
            """
            INSERT OR REPLACE INTO timeline_event_links (
                link_id, event_id, entity_id, entity_name, entity_type, role
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                link["link_id"],
                link["event_id"],
                link["entity_id"],
                link.get("entity_name", ""),
                link.get("entity_type", ""),
                link.get("role", ""),
            ),
        )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_int(value: str) -> int | None:
    value = value.strip().replace(",", "")
    return int(value) if value else None


def parse_float(value: str) -> float | None:
    value = value.strip().replace(",", "")
    return float(value) if value else None


def insert_shareholder_reviews(connection: sqlite3.Connection) -> tuple[int, int]:
    if not SHAREHOLDER_REVIEW_ROOT.exists():
        return (0, 0)

    imported_tables = 0
    imported_rows = 0
    for review_dir in sorted(path for path in SHAREHOLDER_REVIEW_ROOT.iterdir() if path.is_dir()):
        table_path = review_dir / "shareholder_tables_reviewed.csv"
        row_path = review_dir / "shareholder_rows_reviewed.csv"
        if not table_path.exists() or not row_path.exists():
            continue

        reviewed_tables = {
            row["table_id"]: row
            for row in read_csv(table_path)
            if row.get("review_status") == "reviewed"
        }

        for table in reviewed_tables.values():
            connection.execute(
                """
                INSERT OR REPLACE INTO shareholder_tables (
                    table_id, source_id, pdf_page, printed_page, table_title,
                    company_or_subject_original, data_date, ocr_page_json, source_pdf,
                    review_status, reviewer, reviewed_at, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table["table_id"],
                    table["source_id"],
                    parse_int(table["pdf_page"]),
                    table.get("printed_page", ""),
                    table["table_title"],
                    table["company_or_subject_original"],
                    table.get("data_date", ""),
                    table["ocr_page_json"],
                    table["source_pdf"],
                    table["review_status"],
                    table["reviewer"],
                    table["reviewed_at"],
                    table.get("notes", ""),
                ),
            )
            imported_tables += 1

        for row in read_csv(row_path):
            if row.get("review_status") != "reviewed":
                continue
            if row.get("table_id") not in reviewed_tables:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO shareholder_rows (
                    row_id, table_id, source_id, pdf_page, printed_page, table_title,
                    company_or_subject_original, data_date, rank, shareholder_name_original,
                    shareholder_name_normalized, shareholder_entity_id, location_original,
                    shares, share_unit, amount_yen, ownership_percent, ocr_quote,
                    ocr_page_json, source_pdf, review_status, reviewer, reviewed_at, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["row_id"],
                    row["table_id"],
                    row["source_id"],
                    parse_int(row["pdf_page"]),
                    row.get("printed_page", ""),
                    row.get("table_title", ""),
                    row.get("company_or_subject_original", ""),
                    row.get("data_date", ""),
                    parse_int(row.get("rank", "")),
                    row["shareholder_name_original"],
                    row.get("shareholder_name_normalized", ""),
                    row.get("shareholder_entity_id", ""),
                    row.get("location_original", ""),
                    parse_int(row.get("shares", "")),
                    row.get("share_unit", ""),
                    parse_float(row.get("amount_yen", "")),
                    parse_float(row.get("ownership_percent", "")),
                    row["ocr_quote"],
                    row["ocr_page_json"],
                    row["source_pdf"],
                    row["review_status"],
                    row["reviewer"],
                    row["reviewed_at"],
                    row.get("notes", ""),
                ),
            )
            imported_rows += 1

    return (imported_tables, imported_rows)


def officer_entity_id(source_id: str, entity_type: str, name: str) -> str:
    return f"officer_ent_{stable_hash(source_id, entity_type, name)}"


def officer_relation_type(role_original: str, role_normalized: str) -> str:
    return (
        OFFICER_ROLE_RELATION_TYPES.get(role_normalized)
        or OFFICER_ROLE_RELATION_TYPES.get(role_original)
        or "officer_of"
    )


def parse_overlap_organization(value: Any) -> dict[str, str]:
    item = str(value or "").strip(" \t\r\n、，,")
    if not item:
        return {
            "organization_name": "",
            "relationship_type": "affiliated_with",
            "observed_marker": "",
            "parse_confidence": "low",
            "parse_note": "Empty overlap item.",
        }
    for suffix, relation_type in OVERLAP_ROLE_SUFFIXES:
        if item.endswith(suffix) and len(item) > len(suffix):
            organization = item[: -len(suffix)].strip(" \t\r\n、，,")
            if organization:
                confidence = "low" if suffix in {"会", "會"} else "medium"
                note = (
                    f"Parsed final `{suffix}` as an overlap role marker."
                    if suffix not in {"会", "會"}
                    else (
                        f"Parsed final `{suffix}` as a possible chair marker; "
                        "review because it may also be part of an institution name."
                    )
                )
                return {
                    "organization_name": organization,
                    "relationship_type": relation_type,
                    "observed_marker": suffix,
                    "parse_confidence": confidence,
                    "parse_note": note,
                }
    if item.endswith("社"):
        return {
            "organization_name": item,
            "relationship_type": "affiliated_with",
            "observed_marker": "社",
            "parse_confidence": "medium",
            "parse_note": "`社` preserved as part of the institution name, not parsed as a role marker.",
        }
    return {
        "organization_name": item,
        "relationship_type": "affiliated_with",
        "observed_marker": "",
        "parse_confidence": "low",
        "parse_note": "No reviewed overlap role marker found; preserved full item.",
    }


def insert_projected_entity(
    connection: sqlite3.Connection,
    entity_id: str,
    name: str,
    entity_type: str,
    notes: str,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO evidence_entities (
            entity_id, canonical_name, name_original, entity_type, aliases_json, notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_id, name, name, entity_type, json.dumps([], ensure_ascii=False), notes),
    )


def insert_projected_quote(
    connection: sqlite3.Connection,
    evidence_id: str,
    source_id: str,
    page: int,
    quote: str,
    ocr_page_json: str,
    source_pdf: str,
    note: str,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO evidence_quotes (
            evidence_id, source_id, page, quote, ocr_page_json, source_pdf,
            note, extraction_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (evidence_id, source_id, page, quote, ocr_page_json, source_pdf, note, "reviewed"),
    )


def insert_projected_mention(
    connection: sqlite3.Connection,
    mention_id: str,
    entity_id: str,
    source_id: str,
    page: int,
    name: str,
    evidence_id: str,
    note: str,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO evidence_mentions (
            mention_id, entity_id, source_id, page, name_as_appears,
            evidence_id, confidence, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mention_id, entity_id, source_id, page, name, evidence_id, "medium", note),
    )


def insert_projected_relationship(
    connection: sqlite3.Connection,
    relationship_id: str,
    subject_entity_id: str,
    object_entity_id: str,
    relation_type: str,
    source_id: str,
    page: int,
    evidence_id: str,
    quote: str,
    confidence: str,
    note: str,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO relationship_claims (
            relationship_id, subject_entity_id, object_entity_id, relation_type,
            source_id, page, evidence_id, quote, confidence, note, extraction_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            relationship_id,
            subject_entity_id,
            object_entity_id,
            relation_type,
            source_id,
            page,
            evidence_id,
            quote,
            confidence,
            note,
            "reviewed",
        ),
    )


def insert_officer_evidence_projection(
    connection: sqlite3.Connection,
    artifact_id: str,
    table: dict[str, Any],
    term: dict[str, Any],
    projected_relationship_ids: set[str],
) -> int:
    source_id = term["source_id"]
    page = parse_int(str(term["pdf_page"])) or 0
    table_id = term["table_id"]
    term_id = term["term_id"]
    printed_page = str(term.get("printed_page") or table.get("printed_page") or "")
    table_title = table["table_title"]
    source_pdf = table["source_pdf"]
    ocr_page_json = table.get("ocr_page_json", "")
    confidence = term.get("confidence", "medium") or "medium"
    person_name = term["person_name_original"]
    organization_name = term["organization_name_original"]

    person_entity_id = term.get("person_entity_id") or officer_entity_id(source_id, "person", person_name)
    organization_entity_id = (
        term.get("organization_entity_id")
        or table.get("organization_entity_id")
        or officer_entity_id(source_id, "organization", organization_name)
    )
    base_note = (
        f"Derived from secondary-scholarship officer table; artifact_id={artifact_id}; "
        f"table_id={table_id}; term_id={term_id}; printed_page={printed_page}. "
        "Not a primary-source claim."
    )

    insert_projected_entity(connection, person_entity_id, person_name, "person", base_note)
    insert_projected_entity(connection, organization_entity_id, organization_name, "organization", base_note)

    quote = term.get("evidence_quote") or (
        f"{person_name}｜{term.get('era_start', '')}={term.get('role_original', '')}"
        f"（{term.get('role_normalized', '')}）｜{table_title}"
    )
    evidence_id = f"officer_ev_{stable_hash(artifact_id, term_id, 'main')}"
    relation_type = officer_relation_type(term.get("role_original", ""), term.get("role_normalized", ""))
    relationship_id = f"officer_rel_{stable_hash(artifact_id, term_id, 'main')}"
    insert_projected_quote(connection, evidence_id, source_id, page, quote, ocr_page_json, source_pdf, base_note)
    insert_projected_mention(
        connection,
        f"officer_m_{stable_hash(evidence_id, person_entity_id)}",
        person_entity_id,
        source_id,
        page,
        person_name,
        evidence_id,
        base_note,
    )
    insert_projected_mention(
        connection,
        f"officer_m_{stable_hash(evidence_id, organization_entity_id)}",
        organization_entity_id,
        source_id,
        page,
        organization_name,
        evidence_id,
        base_note,
    )
    insert_projected_relationship(
        connection,
        relationship_id,
        person_entity_id,
        organization_entity_id,
        relation_type,
        source_id,
        page,
        evidence_id,
        quote,
        confidence,
        base_note,
    )
    projected_relationship_ids.add(relationship_id)
    projected_relationships = 1

    for overlap_item in term.get("overlap_organizations", []) or []:
        overlap_original = str(overlap_item or "").strip()
        overlap_parse = parse_overlap_organization(overlap_original)
        overlap_name = overlap_parse["organization_name"]
        overlap_relation_type = overlap_parse["relationship_type"]
        if not overlap_name:
            continue
        overlap_relationship_id = (
            f"officer_rel_{stable_hash(artifact_id, table_id, person_name, 'overlap', overlap_original)}"
        )
        if overlap_relationship_id in projected_relationship_ids:
            continue
        overlap_entity_id = officer_entity_id(source_id, "organization", overlap_name)
        overlap_note = (
            f"{base_note} Derived from overlap note item `{overlap_original}`"
            f"; parsed organization `{overlap_name}`"
            f"; observed_marker `{overlap_parse['observed_marker']}`"
            f"; parse_confidence `{overlap_parse['parse_confidence']}`"
            f"; parse_note {overlap_parse['parse_note']} "
            f"Full overlap_text={term.get('overlap_text', '')}"
        )
        overlap_quote = f"{person_name}｜{overlap_original}｜兼職状況｜{table_title}"
        overlap_evidence_id = (
            f"officer_ev_{stable_hash(artifact_id, table_id, person_name, 'overlap', overlap_original)}"
        )
        insert_projected_entity(connection, overlap_entity_id, overlap_name, "organization", overlap_note)
        insert_projected_quote(
            connection,
            overlap_evidence_id,
            source_id,
            page,
            overlap_quote,
            ocr_page_json,
            source_pdf,
            overlap_note,
        )
        insert_projected_mention(
            connection,
            f"officer_m_{stable_hash(overlap_evidence_id, person_entity_id)}",
            person_entity_id,
            source_id,
            page,
            person_name,
            overlap_evidence_id,
            overlap_note,
        )
        insert_projected_mention(
            connection,
            f"officer_m_{stable_hash(overlap_evidence_id, overlap_entity_id)}",
            overlap_entity_id,
            source_id,
            page,
            overlap_name,
            overlap_evidence_id,
            overlap_note,
        )
        insert_projected_relationship(
            connection,
            overlap_relationship_id,
            person_entity_id,
            overlap_entity_id,
            overlap_relation_type,
            source_id,
            page,
            overlap_evidence_id,
            overlap_quote,
            confidence,
            overlap_note,
        )
        projected_relationship_ids.add(overlap_relationship_id)
        projected_relationships += 1

    return projected_relationships


def insert_officer_table_extraction(
    connection: sqlite3.Connection, extraction: dict[str, Any], artifact_path: Path
) -> tuple[int, int, int]:
    """Import reviewed secondary-source officer timeline rows from JSON artifacts."""

    reviewed_tables = {
        table["table_id"]: table
        for table in extraction.get("organization_officer_tables", [])
        if isinstance(table, dict) and table.get("review_status") == "reviewed"
    }
    if not reviewed_tables:
        return (0, 0, 0)

    artifact_id = extraction.get("artifact_id", artifact_path.stem)
    imported_tables = 0
    imported_terms = 0
    projected_relationships = 0
    projected_relationship_ids: set[str] = set()

    for table in reviewed_tables.values():
        connection.execute(
            """
            INSERT OR REPLACE INTO organization_officer_tables (
                table_id, artifact_id, source_id, pdf_page, printed_page, table_title,
                organization_name_original, organization_entity_id, source_pdf,
                page_image, crop_image, crop_region_json, ocr_page_json,
                parse_artifact_path, parsing_engine, review_status, reviewer,
                reviewed_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                table["table_id"],
                artifact_id,
                table["source_id"],
                parse_int(str(table["pdf_page"])),
                table.get("printed_page", ""),
                table["table_title"],
                table["organization_name_original"],
                table.get("organization_entity_id", ""),
                table["source_pdf"],
                table.get("page_image", ""),
                table.get("crop_image", ""),
                json.dumps(table.get("crop_region", {}), ensure_ascii=False),
                table.get("ocr_page_json", ""),
                artifact_path.relative_to(ROOT).as_posix(),
                table.get("parsing_engine", ""),
                table["review_status"],
                table["reviewer"],
                table["reviewed_at"],
                table.get("notes", ""),
            ),
        )
        imported_tables += 1

    for term in extraction.get("organization_officer_terms", []):
        if not isinstance(term, dict):
            continue
        if term.get("review_status") != "reviewed":
            continue
        if term.get("table_id") not in reviewed_tables:
            continue
        connection.execute(
            """
            INSERT OR REPLACE INTO organization_officer_terms (
                term_id, table_id, artifact_id, source_id, pdf_page, printed_page,
                person_name_original, person_name_normalized, person_entity_id,
                organization_name_original, organization_entity_id, role_original,
                role_normalized, date_start, date_end, era_start, era_end,
                status_original, overlap_text, overlap_organizations_json,
                evidence_quote, crop_region_id, confidence, review_status, reviewer,
                reviewed_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                term["term_id"],
                term["table_id"],
                artifact_id,
                term["source_id"],
                parse_int(str(term["pdf_page"])),
                term.get("printed_page", ""),
                term["person_name_original"],
                term.get("person_name_normalized", ""),
                term.get("person_entity_id", ""),
                term["organization_name_original"],
                term.get("organization_entity_id", ""),
                term["role_original"],
                term["role_normalized"],
                term.get("date_start", ""),
                term.get("date_end", ""),
                term.get("era_start", ""),
                term.get("era_end", ""),
                term.get("status_original", ""),
                term.get("overlap_text", ""),
                json.dumps(term.get("overlap_organizations", []), ensure_ascii=False),
                term["evidence_quote"],
                term.get("crop_region_id", ""),
                term.get("confidence", ""),
                term["review_status"],
                term["reviewer"],
                term["reviewed_at"],
                term.get("notes", ""),
            ),
        )
        imported_terms += 1
        projected_relationships += insert_officer_evidence_projection(
            connection,
            artifact_id,
            reviewed_tables[term["table_id"]],
            term,
            projected_relationship_ids,
        )

    return (imported_tables, imported_terms, projected_relationships)


def main() -> int:
    connection = connect()
    create_schema(connection)

    source_ids = insert_sources(connection)
    imported = 0
    skipped = 0

    source_map = {
        source["source_id"]: source
        for source in load_json(SOURCES_PATH)
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    for path in sorted(EXTRACTIONS_DIR.glob("*.json")):
        extraction = load_json(path)
        source_id = extraction["source_id"]
        if source_is_excluded(source_id):
            skipped += 1
            continue
        source = source_map.get(source_id, extraction)
        if not source_is_resolved(source):
            skipped += 1
            continue
        insert_source_from_extraction(connection, extraction, source_ids)
        if extraction.get("extraction_schema_version") == "evidence-graph-v1":
            insert_evidence_extraction(connection, extraction)
        status = extraction.get("provenance", {}).get("status")
        if status != "reviewed":
            skipped += 1
            continue
        insert_extraction(connection, extraction)
        imported += 1

    shareholder_tables, shareholder_rows = insert_shareholder_reviews(connection)
    officer_tables = 0
    officer_terms = 0
    officer_projected_relationships = 0
    for path in sorted(EXTRACTIONS_DIR.glob("*.json")):
        extraction = load_json(path)
        source_id = extraction["source_id"]
        if source_is_excluded(source_id) or not source_is_resolved(source_map.get(source_id, extraction)):
            continue
        tables, terms, projected_relationships = insert_officer_table_extraction(connection, extraction, path)
        officer_tables += tables
        officer_terms += terms
        officer_projected_relationships += projected_relationships

    connection.commit()
    connection.close()

    print(
        f"Built {DB_PATH} with {imported} reviewed document(s); skipped {skipped}; "
        f"imported {shareholder_tables} shareholder table(s), {shareholder_rows} row(s); "
        f"imported {officer_tables} officer table(s), {officer_terms} term(s); "
        f"projected {officer_projected_relationships} officer relationship(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
