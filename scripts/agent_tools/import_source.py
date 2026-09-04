#!/usr/bin/env python3
"""
Agent CLI Tool: Import PDF or Image sources into Standalone OCR Desk.
Copies input files into sources/raw/ and auto-registers metadata in sources/metadata/sources.json.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SOURCES_RAW = ROOT_DIR / "sources" / "raw"
SOURCES_META = ROOT_DIR / "sources" / "metadata" / "sources.json"


def natural_sort_key(s: str) -> list[int | str]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def convert_images_to_pdf(image_paths: list[Path], output_pdf: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("[!] Error: Pillow package is required for image conversion.")
        sys.exit(1)

    images = []
    for p in image_paths:
        try:
            img = Image.open(p).convert("RGB")
            images.append(img)
        except Exception as e:
            print(f"[!] Warning: Skipping image {p.name}: {e}")

    if not images:
        print("[!] Error: No valid images to convert.")
        sys.exit(1)

    images[0].save(output_pdf, format="PDF", save_all=True, append_images=images[1:])


def load_sources_metadata() -> list[dict]:
    if SOURCES_META.exists():
        try:
            with open(SOURCES_META, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_sources_metadata(records: list[dict]) -> None:
    SOURCES_META.parent.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_META, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def import_files(file_paths: list[Path], custom_title: str | None = None) -> list[dict]:
    SOURCES_RAW.mkdir(parents=True, exist_ok=True)
    records = load_sources_metadata()

    existing_ids = {r.get("source_id") for r in records}
    imported_records = []

    for file_path in file_paths:
        if not file_path.exists():
            print(f"[!] File not found: {file_path}")
            continue

        ext = file_path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"):
            pdf_filename = file_path.stem + ".pdf"
            dest_path = SOURCES_RAW / pdf_filename
            print(f"[*] Converting single image {file_path.name} to {pdf_filename}...")
            convert_images_to_pdf([file_path], dest_path)
            imported_filename = pdf_filename
        elif ext == ".pdf":
            dest_path = SOURCES_RAW / file_path.name
            shutil.copy2(file_path, dest_path)
            imported_filename = file_path.name
        else:
            print(f"[!] Unsupported file type: {ext} for {file_path.name}")
            continue

        source_id = Path(imported_filename).stem.replace(" ", "_")
        title = custom_title if custom_title else Path(imported_filename).stem.replace("_", " ").replace("-", " ")

        new_record = {
            "source_id": source_id,
            "title": title,
            "title_original": title,
            "local_pdf": f"sources/raw/{imported_filename}",
            "volume_number": 1,
            "publication_year": "",
            "collection": "Imported",
            "category": "General",
        }

        # Replace existing record if matching source_id, otherwise append
        records = [r for r in records if r.get("source_id") != source_id]
        records.append(new_record)
        imported_records.append(new_record)
        print(f"[✓] Imported: {source_id} -> {dest_path}")

    save_sources_metadata(records)
    return imported_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Import PDF/Image sources into Standalone OCR Desk.")
    parser.add_argument("files", nargs="+", help="Paths to PDF or image files to import")
    parser.add_argument("--title", help="Custom title for the source")

    args = parser.parse_args()
    paths = [Path(f).resolve() for f in args.files]
    imported = import_files(paths, custom_title=args.title)
    print(f"\n[✓] Successfully imported {len(imported)} source(s).")


if __name__ == "__main__":
    main()
