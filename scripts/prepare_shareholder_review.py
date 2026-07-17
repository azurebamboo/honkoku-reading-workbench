#!/usr/bin/env python3
"""Prepare review CSVs and side-by-side HTML for shareholder table OCR."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "sources" / "raw"
SOURCES_PATH = ROOT / "sources" / "metadata" / "sources.json"
OCR_RAW_ROOT = ROOT / "artifacts" / "ocr" / "raw"
SHAREHOLDER_REVIEW_ROOT = ROOT / "artifacts" / "shareholders" / "review"
DEFAULT_SOURCE_ID = "raw_f344c3ccb490"
DEFAULT_PAGES = [15, 16, 20, 28]

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


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_sources() -> list[dict[str, Any]]:
    return load_json(SOURCES_PATH)


def find_source(source_id: str) -> dict[str, Any]:
    for record in load_sources():
        if record["source_id"] == source_id:
            return record
    raise SystemExit(f"Source not found in metadata: {source_id}")


def parse_pages(value: str) -> list[int]:
    pages: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(piece) for piece in part.split("-", 1)]
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    if not pages or min(pages) < 1:
        raise SystemExit("Pages must be one-based positive numbers.")
    return sorted(set(pages))


def render_images(pdf_path: Path, pages: list[int], image_dir: Path, scale: float) -> dict[int, Path]:
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing pypdfium2; run through the uv environment.") from exc

    image_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[int, Path] = {}
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_number in pages:
            if page_number > len(pdf):
                raise SystemExit(f"Page {page_number} is outside PDF page count {len(pdf)}.")
            page = pdf[page_number - 1]
            image = page.render(scale=scale).to_pil()
            output_path = image_dir / f"page_{page_number:04d}.png"
            image.save(output_path)
            rendered[page_number] = output_path
    finally:
        pdf.close()
    return rendered


def iter_text_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            items.append(value)
        for child in value.values():
            items.extend(iter_text_items(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(iter_text_items(child))
    return items


def item_sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
    box = item.get("boundingBox") or []
    xs = [point[0] for point in box if isinstance(point, list) and len(point) >= 2]
    ys = [point[1] for point in box if isinstance(point, list) and len(point) >= 2]
    x = min(xs) if xs else 0
    y = min(ys) if ys else 0
    vertical = 0 if item.get("isVertical") == "true" else 1
    return (vertical, x, y)


def extract_page_text(page_json: dict[str, Any]) -> list[str]:
    items = sorted(iter_text_items(page_json.get("contents", [])), key=item_sort_key)
    return [re.sub(r"\s+", " ", item["text"]).strip() for item in items if item.get("text")]


def numeric_value(text: str, suffix: str | None = None) -> str:
    if suffix:
        pattern = rf"([0-9][0-9,\.]*)\s*{re.escape(suffix)}"
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(",", "")
    matches = re.findall(r"[0-9][0-9,\.]*", text)
    return matches[-1].replace(",", "") if matches else ""


def integer_value(text: str, suffix: str | None = None) -> str:
    if suffix:
        pattern = rf"([0-9][0-9,]*)\s*{re.escape(suffix)}"
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(",", "")
    matches = re.findall(r"[0-9][0-9,]*", text)
    return matches[-1].replace(",", "") if matches else ""


def guess_rank(text: str) -> str:
    match = re.match(r"^\s*[（(]?([0-9]{1,3})[）).、\s]", text)
    return match.group(1) if match else ""


def guess_name(text: str) -> str:
    cleaned = re.sub(r"[0-9０-９,.\s株円圓%％割分厘第表年月日]", "", text)
    cleaned = re.sub(r"[()（）:：;；・、。]", "", cleaned)
    if 2 <= len(cleaned) <= 24 and not re.search(r"株主|合計|合本|会社|會社|資料|出所", cleaned):
        return cleaned
    return ""


def table_id_for(source_id: str, page: int) -> str:
    return f"sharetbl_{source_id}_p{page:04d}_01"


def build_tables(record: dict[str, Any], pages: list[int]) -> list[dict[str, str]]:
    rows = []
    source_pdf = f"sources/raw/{record['local_pdf']}"
    for page in pages:
        table_id = table_id_for(record["source_id"], page)
        rows.append(
            {
                "table_id": table_id,
                "source_id": record["source_id"],
                "pdf_page": str(page),
                "printed_page": "",
                "table_title": "",
                "company_or_subject_original": "",
                "data_date": "",
                "ocr_page_json": f"artifacts/ocr/raw/{record['source_id']}/pages/page_{page:04d}.json",
                "source_pdf": source_pdf,
                "review_status": "needs_review",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "Draft table metadata seeded from OCR review preparation.",
            }
        )
    return rows


def build_rows(record: dict[str, Any], pages: list[int]) -> tuple[list[dict[str, str]], dict[int, list[str]]]:
    seeded_rows: list[dict[str, str]] = []
    page_text: dict[int, list[str]] = {}
    source_pdf = f"sources/raw/{record['local_pdf']}"
    for page in pages:
        page_json_path = ROOT / "artifacts" / "ocr" / "raw" / record["source_id"] / "pages" / f"page_{page:04d}.json"
        if not page_json_path.exists():
            raise SystemExit(f"Missing OCR page JSON: {page_json_path}")
        page_json = load_json(page_json_path)
        lines = extract_page_text(page_json)
        page_text[page] = lines
        table_id = table_id_for(record["source_id"], page)
        candidate_lines = [
            line for line in lines
            if re.search(r"[0-9０-９]", line) or "株" in line or "株主" in line
        ]
        if not candidate_lines:
            candidate_lines = lines
        for index, line in enumerate(candidate_lines, start=1):
            shares = integer_value(line, "株")
            amount_yen = numeric_value(line, "円") or numeric_value(line, "圓")
            seeded_rows.append(
                {
                    "table_id": table_id,
                    "row_id": f"{table_id}_r{index:03d}",
                    "source_id": record["source_id"],
                    "pdf_page": str(page),
                    "printed_page": "",
                    "table_title": "",
                    "company_or_subject_original": "",
                    "data_date": "",
                    "rank": guess_rank(line),
                    "shareholder_name_original": guess_name(line),
                    "shareholder_name_normalized": "",
                    "shareholder_entity_id": "",
                    "location_original": "",
                    "shares": shares,
                    "share_unit": "株" if shares else "",
                    "amount_yen": amount_yen,
                    "ownership_percent": numeric_value(line, "%") or numeric_value(line, "％"),
                    "ocr_quote": line,
                    "ocr_page_json": page_json_path.relative_to(ROOT).as_posix(),
                    "source_pdf": source_pdf,
                    "review_status": "needs_review",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": "Draft row; verify against page image before marking reviewed.",
                }
            )
    return seeded_rows, page_text


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_html(
    path: Path,
    record: dict[str, Any],
    pages: list[int],
    images: dict[int, Path],
    page_text: dict[int, list[str]],
    rows: list[dict[str, str]],
) -> None:
    rows_by_page: dict[int, list[dict[str, str]]] = {page: [] for page in pages}
    for row in rows:
        rows_by_page[int(row["pdf_page"])].append(row)

    sections: list[str] = []
    for page in pages:
        image_rel = images[page].relative_to(path.parent).as_posix()
        ocr_lines = "\n".join(page_text.get(page, []))
        row_markup = "\n".join(
            "<tr>"
            f"<td>{html.escape(row['row_id'])}</td>"
            f"<td>{html.escape(row['rank'])}</td>"
            f"<td>{html.escape(row['shareholder_name_original'])}</td>"
            f"<td>{html.escape(row['shares'])}</td>"
            f"<td>{html.escape(row['ocr_quote'])}</td>"
            "</tr>"
            for row in rows_by_page.get(page, [])
        )
        sections.append(
            f"""
            <section class="pageBlock">
              <header>
                <h2>PDF page {page}</h2>
                <p><code>artifacts/ocr/raw/{record['source_id']}/pages/page_{page:04d}.json</code></p>
              </header>
              <div class="sideBySide">
                <figure>
                  <img src="{html.escape(image_rel)}" alt="PDF page {page}">
                </figure>
                <div class="ocrPane">
                  <h3>OCR Text</h3>
                  <pre>{html.escape(ocr_lines)}</pre>
                </div>
              </div>
              <h3>Draft CSV Rows</h3>
              <table>
                <thead>
                  <tr><th>Row ID</th><th>Rank</th><th>Name Guess</th><th>Shares</th><th>OCR Quote</th></tr>
                </thead>
                <tbody>{row_markup}</tbody>
              </table>
            </section>
            """
        )

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shareholder Table Review - {html.escape(record['title'])}</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172026; background: #f6f4ef; }}
    header.hero {{ padding: 24px 32px; background: #263238; color: white; }}
    main {{ padding: 24px 32px; }}
    code {{ background: rgba(0,0,0,0.08); padding: 2px 5px; border-radius: 4px; }}
    .pageBlock {{ margin: 0 0 32px; padding: 20px; background: white; border: 1px solid #d8d3c8; border-radius: 8px; }}
    .sideBySide {{ display: grid; grid-template-columns: minmax(280px, 0.9fr) minmax(320px, 1.1fr); gap: 20px; align-items: start; }}
    figure {{ margin: 0; max-height: 760px; overflow: auto; border: 1px solid #d8d3c8; background: #eee; }}
    img {{ width: 100%; display: block; }}
    .ocrPane pre {{ white-space: pre-wrap; line-height: 1.7; max-height: 760px; overflow: auto; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd6c8; padding: 6px 8px; vertical-align: top; }}
    th {{ background: #f0ece3; text-align: left; }}
    @media (max-width: 900px) {{ .sideBySide {{ grid-template-columns: 1fr; }} main, header.hero {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <header class="hero">
    <h1>Shareholder Table Review</h1>
    <p>{html.escape(record['title'])} / source <code>{html.escape(record['source_id'])}</code></p>
    <p>Edit <code>shareholder_rows_reviewed.csv</code> and <code>shareholder_tables_reviewed.csv</code>; only rows marked reviewed import into SQLite.</p>
  </header>
  <main>
    {''.join(sections)}
  </main>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare shareholder table review artifacts.")
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--pages", default=",".join(str(page) for page in DEFAULT_PAGES))
    parser.add_argument("--image-scale", type=float, default=1.5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    record = find_source(args.source_id)
    pages = parse_pages(args.pages)
    review_dir = SHAREHOLDER_REVIEW_ROOT / record["source_id"]
    image_dir = review_dir / "images"
    pdf_path = RAW_ROOT / record["local_pdf"]
    if not pdf_path.exists():
        raise SystemExit(f"Raw PDF missing: {pdf_path}")

    images = render_images(pdf_path, pages, image_dir, args.image_scale)
    tables = build_tables(record, pages)
    rows, page_text = build_rows(record, pages)

    write_csv(review_dir / "shareholder_tables_draft.csv", TABLE_COLUMNS, tables, overwrite=True)
    write_csv(review_dir / "shareholder_rows_draft.csv", ROW_COLUMNS, rows, overwrite=True)
    write_csv(review_dir / "shareholder_tables_reviewed.csv", TABLE_COLUMNS, tables, overwrite=args.overwrite)
    write_csv(review_dir / "shareholder_rows_reviewed.csv", ROW_COLUMNS, rows, overwrite=args.overwrite)
    write_html(review_dir / "review.html", record, pages, images, page_text, rows)

    print(f"Wrote review packet: {review_dir / 'review.html'}")
    print(f"Wrote {len(rows)} draft row(s) across {len(tables)} table placeholder(s).")
    if not args.overwrite:
        print("Existing reviewed CSV files were preserved if present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
