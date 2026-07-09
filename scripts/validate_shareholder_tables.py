#!/usr/bin/env python3
"""Validate review-gated shareholder table CSV artifacts."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_ROOT = ROOT / "artifacts" / "shareholders" / "review"

TABLE_COLUMNS = [
    "table_id",
    "source_id",
    "pdf_page",
    "printed_page",
    "table_title",
    "company_or_subject_original",
    "data_date",
    "ocr_page_json",
    "source_pdf",
    "review_status",
    "reviewer",
    "reviewed_at",
    "notes",
]

ROW_COLUMNS = [
    "table_id",
    "row_id",
    "source_id",
    "pdf_page",
    "printed_page",
    "table_title",
    "company_or_subject_original",
    "data_date",
    "rank",
    "shareholder_name_original",
    "shareholder_name_normalized",
    "shareholder_entity_id",
    "location_original",
    "shares",
    "share_unit",
    "amount_yen",
    "ownership_percent",
    "ocr_quote",
    "ocr_page_json",
    "source_pdf",
    "review_status",
    "reviewer",
    "reviewed_at",
    "notes",
]

ALLOWED_STATUSES = {"needs_review", "reviewed", "skip"}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def is_int(value: str) -> bool:
    if value == "":
        return True
    try:
        int(value.replace(",", ""))
    except ValueError:
        return False
    return True


def is_float(value: str) -> bool:
    if value == "":
        return True
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def validate_columns(path: Path, actual: list[str], expected: list[str]) -> list[str]:
    missing = [column for column in expected if column not in actual]
    extra = [column for column in actual if column not in expected]
    errors = []
    if missing:
        errors.append(f"{path}: missing columns {missing}")
    if extra:
        errors.append(f"{path}: unexpected columns {extra}")
    return errors


def validate_table_rows(path: Path, rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        table_id = row.get("table_id", "")
        if not table_id:
            errors.append(f"{path}:{index}: table_id is required")
        elif table_id in seen:
            errors.append(f"{path}:{index}: duplicate table_id {table_id}")
        seen.add(table_id)
        if row.get("review_status") not in ALLOWED_STATUSES:
            errors.append(f"{path}:{index}: invalid review_status {row.get('review_status')}")
        if not is_int(row.get("pdf_page", "")):
            errors.append(f"{path}:{index}: pdf_page must be an integer")
        for field in ("ocr_page_json", "source_pdf"):
            value = row.get(field, "")
            if value and not (ROOT / value).exists():
                errors.append(f"{path}:{index}: {field} does not exist: {value}")
        if row.get("review_status") == "reviewed":
            for field in ("reviewer", "reviewed_at", "table_title", "company_or_subject_original"):
                if not row.get(field, ""):
                    errors.append(f"{path}:{index}: reviewed table requires {field}")
    return errors


def validate_data_rows(
    path: Path,
    rows: list[dict[str, str]],
    table_statuses: dict[str, str],
) -> tuple[list[str], int]:
    errors: list[str] = []
    importable = 0
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        row_id = row.get("row_id", "")
        table_id = row.get("table_id", "")
        if not row_id:
            errors.append(f"{path}:{index}: row_id is required")
        elif row_id in seen:
            errors.append(f"{path}:{index}: duplicate row_id {row_id}")
        seen.add(row_id)
        if table_id not in table_statuses:
            errors.append(f"{path}:{index}: table_id does not resolve: {table_id}")
        if row.get("review_status") not in ALLOWED_STATUSES:
            errors.append(f"{path}:{index}: invalid review_status {row.get('review_status')}")
        for field in ("pdf_page", "rank", "shares"):
            if not is_int(row.get(field, "")):
                errors.append(f"{path}:{index}: {field} must be an integer")
        for field in ("amount_yen", "ownership_percent"):
            if not is_float(row.get(field, "")):
                errors.append(f"{path}:{index}: {field} must be numeric")
        for field in ("ocr_page_json", "source_pdf"):
            value = row.get(field, "")
            if value and not (ROOT / value).exists():
                errors.append(f"{path}:{index}: {field} does not exist: {value}")
        if row.get("review_status") == "reviewed":
            if table_statuses.get(table_id) != "reviewed":
                errors.append(f"{path}:{index}: reviewed row requires reviewed table {table_id}")
            for field in ("reviewer", "reviewed_at", "shareholder_name_original", "ocr_quote"):
                if not row.get(field, ""):
                    errors.append(f"{path}:{index}: reviewed row requires {field}")
            importable += 1
    return errors, importable


def validate_review_dir(review_dir: Path) -> tuple[list[str], int, int]:
    errors: list[str] = []
    table_path = review_dir / "shareholder_tables_reviewed.csv"
    row_path = review_dir / "shareholder_rows_reviewed.csv"
    if not table_path.exists():
        return [f"{review_dir}: missing shareholder_tables_reviewed.csv"], 0, 0
    if not row_path.exists():
        return [f"{review_dir}: missing shareholder_rows_reviewed.csv"], 0, 0

    table_columns, table_rows = read_csv(table_path)
    row_columns, data_rows = read_csv(row_path)
    errors.extend(validate_columns(table_path, table_columns, TABLE_COLUMNS))
    errors.extend(validate_columns(row_path, row_columns, ROW_COLUMNS))
    table_statuses = {row.get("table_id", ""): row.get("review_status", "") for row in table_rows}
    errors.extend(validate_table_rows(table_path, table_rows))
    row_errors, importable = validate_data_rows(row_path, data_rows, table_statuses)
    errors.extend(row_errors)
    return errors, len(table_rows), importable


def main() -> int:
    review_dirs = [path for path in sorted(REVIEW_ROOT.iterdir()) if path.is_dir()] if REVIEW_ROOT.exists() else []
    if not review_dirs:
        print("No shareholder review artifacts found.")
        return 0

    errors: list[str] = []
    table_count = 0
    importable_count = 0
    for review_dir in review_dirs:
        review_errors, tables, importable = validate_review_dir(review_dir)
        errors.extend(review_errors)
        table_count += tables
        importable_count += importable

    if errors:
        print("Shareholder table validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"Validated {len(review_dirs)} shareholder review packet(s), "
        f"{table_count} table placeholder(s), {importable_count} reviewed importable row(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
