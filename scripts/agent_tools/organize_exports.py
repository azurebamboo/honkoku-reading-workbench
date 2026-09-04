#!/usr/bin/env python3
"""
Agent CLI Tool: Organize, search, and export OCR transcriptions and notes.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
OCR_RAW_DIR = ROOT_DIR / "artifacts" / "ocr" / "raw"
OCR_CORRECTED_DIR = ROOT_DIR / "artifacts" / "ocr" / "corrected"
EXPORTS_DIR = ROOT_DIR / "artifacts" / "exports"


def list_all_ocr_transcriptions() -> list[dict]:
    items = []
    dirs_to_check = [("corrected", OCR_CORRECTED_DIR), ("raw", OCR_RAW_DIR)]

    seen_sources = set()

    for status_type, base_dir in dirs_to_check:
        if not base_dir.exists():
            continue
        for src_dir in base_dir.iterdir():
            if not src_dir.is_dir():
                continue
            source_id = src_dir.name
            if source_id in seen_sources:
                continue
            seen_sources.add(source_id)

            manifest_file = src_dir / "manifest.json"
            page_files = list(src_dir.glob("page_*.json"))
            items.append({
                "source_id": source_id,
                "status_type": status_type,
                "dir_path": src_dir,
                "page_count": len(page_files),
                "has_manifest": manifest_file.exists(),
            })

    return items


def search_transcriptions(query: str) -> list[dict]:
    results = []
    items = list_all_ocr_transcriptions()

    for item in items:
        source_id = item["source_id"]
        src_dir = item["dir_path"]
        matched_pages = []

        for page_file in src_dir.glob("page_*.json"):
            try:
                with open(page_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    text = data.get("text", "") or data.get("transcription", "")
                    if not text and "lines" in data:
                        text = "\n".join(l.get("text", "") if isinstance(l, dict) else str(l) for l in data["lines"])
                    
                    if query.lower() in text.lower():
                        matched_pages.append({
                            "page_file": page_file.name,
                            "snippet": text[:150].replace("\n", " ") + "...",
                        })
            except Exception:
                pass

        if matched_pages:
            results.append({
                "source_id": source_id,
                "matched_count": len(matched_pages),
                "matches": matched_pages,
            })

    return results


def export_project(source_ids: list[str] | None, folder_name: str) -> Path:
    target_export = EXPORTS_DIR / folder_name
    target_export.mkdir(parents=True, exist_ok=True)

    items = list_all_ocr_transcriptions()
    if source_ids:
        items = [item for item in items if item["source_id"] in source_ids]

    exported_count = 0
    for item in items:
        src_id = item["source_id"]
        src_dir = item["dir_path"]
        dest_dir = target_export / src_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        for f in src_dir.glob("*"):
            if f.is_file():
                shutil.copy2(f, dest_dir / f.name)
        exported_count += 1

    print(f"[✓] Exported {exported_count} source directory(ies) to:")
    print(f"    {target_export}")
    return target_export


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize, search, and export OCR transcriptions.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    subparsers.add_parser("list", help="List all available OCR transcriptions and sources")
    
    search_parser = subparsers.add_parser("search", help="Search OCR text across all sources")
    search_parser.add_argument("query", help="Keyword or phrase to search for")

    export_parser = subparsers.add_parser("export", help="Export selected sources into an organized folder")
    export_parser.add_argument("--sources", nargs="*", help="Specific source IDs to export (omitting exports all)")
    export_parser.add_argument("--name", required=True, help="Folder name under artifacts/exports/")

    args = parser.parse_args()

    if args.command == "list":
        items = list_all_ocr_transcriptions()
        print(f"Found {len(items)} OCR source transcription folder(s):\n")
        for item in items:
            print(f" - {item['source_id']} ({item['status_type']}): {item['page_count']} page(s)")
    elif args.command == "search":
        matches = search_transcriptions(args.query)
        print(f"Search results for '{args.query}': {len(matches)} source(s) matched.\n")
        for m in matches:
            print(f"Source: {m['source_id']} ({m['matched_count']} page matches)")
            for page_match in m["matches"][:3]:
                print(f"  * {page_match['page_file']}: {page_match['snippet']}")
    elif args.command == "export":
        export_project(args.sources, args.name)
    else:
        items = list_all_ocr_transcriptions()
        print(f"OCR Workspace contains {len(items)} source transcription folder(s). Use --help for subcommands.")


if __name__ == "__main__":
    main()
