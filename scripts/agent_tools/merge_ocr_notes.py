#!/usr/bin/env python3
"""
Agent CLI Tool: Merge OCR outputs and transcriptions into consolidated Markdown notes.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
OCR_RAW_DIR = ROOT_DIR / "artifacts" / "ocr" / "raw"
OCR_CORRECTED_DIR = ROOT_DIR / "artifacts" / "ocr" / "corrected"
NOTES_OUTPUT_DIR = ROOT_DIR / "artifacts" / "notes"


def natural_sort_key(s: str) -> list[int | str]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def get_source_pages(source_id: str) -> list[dict]:
    pages = []
    # Check corrected directory first
    corr_dir = OCR_CORRECTED_DIR / source_id
    raw_dir = OCR_RAW_DIR / source_id

    target_dir = corr_dir if corr_dir.exists() else raw_dir
    if not target_dir.exists():
        print(f"[!] No OCR directory found for source: {source_id}")
        return []

    page_files = list(target_dir.glob("page_*.json"))
    page_files.sort(key=lambda p: natural_sort_key(p.name))

    for pf in page_files:
        try:
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
                pages.append(data)
        except Exception as e:
            print(f"[!] Warning: Failed reading {pf.name}: {e}")

    return pages


def extract_page_text(page_data: dict) -> str:
    lines = []
    # Try transcription field first
    if page_data.get("text"):
        return page_data["text"]
    if page_data.get("transcription"):
        return page_data["transcription"]
    
    # Try line blocks
    for line_obj in page_data.get("lines", []):
        if isinstance(line_obj, dict) and "text" in line_obj:
            lines.append(line_obj["text"])
        elif isinstance(line_obj, str):
            lines.append(line_obj)

    return "\n".join(lines)


def merge_notes(source_ids: list[str], output_file: Path | None = None, title: str | None = None) -> Path:
    NOTES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if not output_file:
        file_stem = "_".join(source_ids) + "_merged"
        output_file = NOTES_OUTPUT_DIR / f"{file_stem}.md"

    doc_title = title if title else f"Merged OCR Transcriptions ({', '.join(source_ids)})"
    content_blocks = [f"# {doc_title}\n"]

    total_pages = 0
    for sid in source_ids:
        pages = get_source_pages(sid)
        if not pages:
            continue
        
        content_blocks.append(f"## Document: {sid}\n")
        for idx, page in enumerate(pages, 1):
            page_num = page.get("page_number", idx)
            page_text = extract_page_text(page)
            content_blocks.append(f"### Page {page_num}\n\n{page_text}\n")
            total_pages += 1

    final_text = "\n".join(content_blocks)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"[✓] Successfully merged {total_pages} page(s) across {len(source_ids)} source(s) into:")
    print(f"    {output_file}")
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge OCR transcriptions into consolidated Markdown notes.")
    parser.add_argument("sources", nargs="+", help="Source IDs to merge (e.g. source1 source2)")
    parser.add_argument("--output", help="Output file path (default: artifacts/notes/<sources>_merged.md)")
    parser.add_argument("--title", help="Title for the merged document")

    args = parser.parse_args()
    out_path = Path(args.output).resolve() if args.output else None
    merge_notes(args.sources, output_file=out_path, title=args.title)


if __name__ == "__main__":
    main()
