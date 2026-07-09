#!/usr/bin/env python3
"""Import manually OCRed text files into tracked OCR artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "sources" / "raw"
SOURCES_PATH = ROOT / "sources" / "metadata" / "sources.json"
OUTPUT_ROOT = ROOT / "artifacts" / "ocr" / "manual"

MANUAL_OCR_DIR_NAMES = {"ocr text", "ocr texts"}
FILENAME_OVERRIDES = {
    "Wakao Ippei - parts OCR results": "若尾逸平-部分.pdf",
}
PAGE_MARKER = re.compile(r"^===\s*(?P<label>.+?)\s*\(p\.(?P<page>\d+)\)\s*===", re.MULTILINE)


def load_sources() -> list[dict[str, Any]]:
    with SOURCES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def source_by_pdf_name() -> dict[str, dict[str, Any]]:
    records = load_sources()
    return {Path(record["local_pdf"]).name: record for record in records}


def find_manual_texts(raw_root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in raw_root.rglob("*"):
        if directory.is_dir() and directory.name.lower() in MANUAL_OCR_DIR_NAMES:
            paths.extend(sorted(directory.glob("*.txt")))
    return sorted(paths)


def source_record_for_text(path: Path, by_pdf_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected_pdf_name = FILENAME_OVERRIDES.get(path.stem, f"{path.stem}.pdf")
    if expected_pdf_name in by_pdf_name:
        return by_pdf_name[expected_pdf_name]
    raise SystemExit(f"Could not map manual OCR text to a source PDF: {path}")


def split_pages(text: str) -> list[tuple[int, str]]:
    matches = list(PAGE_MARKER.finditer(text))
    if not matches:
        return [(1, text.strip())]

    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        page_number = int(match.group("page"))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((page_number, text[start:end].strip()))
    return pages


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_page_json(source_id: str, page_number: int, text: str) -> str:
    pages_dir = OUTPUT_ROOT / source_id / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"page_{page_number:04d}.json"
    lines = [line for line in text.splitlines() if line.strip()]
    page_json = {
        "contents": [
            [
                {
                    "id": index,
                    "text": line,
                    "isTextline": "true",
                    "isManualOcr": "true",
                }
                for index, line in enumerate(lines)
            ]
        ],
        "imginfo": {
            "img_width": None,
            "img_height": None,
            "img_path": "",
            "img_name": f"manual_page_{page_number:04d}.txt",
        },
        "manual_ocr": {
            "page": page_number,
            "line_count": len(lines),
            "text_sha256": text_hash(text),
        },
    }
    with page_path.open("w", encoding="utf-8") as handle:
        json.dump(page_json, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return page_path.relative_to(ROOT).as_posix()


def import_text(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pages = split_pages(text)
    source_id = record["source_id"]
    output_dir = OUTPUT_ROOT / source_id
    output_dir.mkdir(parents=True, exist_ok=True)

    page_json_paths = [write_page_json(source_id, page_number, page_text) for page_number, page_text in pages]
    page_numbers = [page_number for page_number, _ in pages]
    manifest = {
        "source_id": source_id,
        "source_path": record["local_pdf"],
        "checksum_sha256": record.get("checksum_sha256", ""),
        "page_range": f"{page_numbers[0]}-{page_numbers[-1]}" if len(page_numbers) > 1 else str(page_numbers[0]),
        "pages": page_numbers,
        "page_json": page_json_paths,
        "ocr_engine": "manual OCR text",
        "ocr_engine_path": path.relative_to(ROOT).as_posix(),
        "ocr_settings": {
            "source_text_file": path.relative_to(ROOT).as_posix(),
            "page_marker_pattern": PAGE_MARKER.pattern,
            "format": "manual-text-to-page-json",
        },
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Import manual OCR text files into tracked artifacts.")
    parser.add_argument("--raw-root", default=str(RAW_ROOT))
    args = parser.parse_args()

    by_pdf_name = source_by_pdf_name()
    text_paths = find_manual_texts(Path(args.raw_root))
    if not text_paths:
        print("No manual OCR text folders found.")
        return 1

    imported = []
    for text_path in text_paths:
        record = source_record_for_text(text_path, by_pdf_name)
        imported.append(import_text(text_path, record))

    print(f"Imported {len(imported)} manual OCR text file(s).")
    for manifest in imported:
        print(f"- {manifest['source_id']}: {manifest['source_path']} ({len(manifest['pages'])} page record(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
