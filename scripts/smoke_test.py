#!/usr/bin/env python3
"""Run a small end-to-end check against the generated Koshu database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


import os

ROOT = Path(__file__).resolve().parents[1]

ACTIVE_PROJECT_ID = os.environ.get("KOSHU_PROJECT", "default")

def get_project_dir() -> Path:
    if ACTIVE_PROJECT_ID == "default":
        return ROOT
    else:
        return ROOT / "projects" / ACTIVE_PROJECT_ID

DB_PATH = get_project_dir() / "db" / "koshu.sqlite"


def main() -> int:
    if not DB_PATH.exists():
        raise SystemExit("Database is missing. Run `python3 scripts/build_database.py` first.")

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    required_tables = {
        "sources",
        "documents",
        "evidence_quotes",
        "evidence_entities",
        "evidence_mentions",
        "keywords",
        "organization_officer_tables",
        "organization_officer_terms",
    }
    missing_tables = sorted(required_tables - tables)

    counts = {
        table: connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
            "count"
        ]
        for table in required_tables
        if table in tables
    }

    connection.close()

    assert not missing_tables, f"missing expected tables: {', '.join(missing_tables)}"
    assert counts["sources"] > 0, "expected at least one cataloged source"
    if counts["documents"] > 0:
        assert counts["keywords"] > 0, "reviewed documents should include reviewed keywords"
    if counts["organization_officer_terms"] > 0:
        assert counts["organization_officer_tables"] > 0, "officer terms require a reviewed officer table"

    print(
        "Smoke test passed: generated database schema and available research data are consistent "
        f"({counts['documents']} reviewed document(s), {counts['evidence_quotes']} evidence quote(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
