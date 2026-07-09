#!/usr/bin/env python3
"""Inventory local raw PDFs into tracked source metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "sources" / "raw"
DEFAULT_CORPUS_ROOT = RAW_ROOT / "Electricity and energy history in Japan"
OUTPUT_PATH = ROOT / "sources" / "metadata" / "sources.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_id_for(raw_relative_path: str) -> str:
    digest = hashlib.sha1(raw_relative_path.encode("utf-8")).hexdigest()[:12]
    return f"raw_{digest}"


def pdf_page_count(path: Path) -> int | None:
    try:
        output = subprocess.check_output(["file", str(path)], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    match = re.search(r"(\d+)\s+pages?", output)
    if match:
        return int(match.group(1))
    return None


def metadata_for(path: Path, corpus_root: Path) -> dict[str, Any]:
    raw_relative_path = path.relative_to(RAW_ROOT).as_posix()
    corpus_relative_path = path.relative_to(corpus_root)
    category = corpus_relative_path.parts[0] if len(corpus_relative_path.parts) > 1 else ""
    stat = path.stat()
    title = path.stem

    return {
        "source_id": source_id_for(raw_relative_path),
        "collection": corpus_root.name,
        "category": category,
        "repository": "",
        "call_number": "",
        "citation": "",
        "title": title,
        "title_original": title,
        "date": "",
        "date_certainty": "unknown",
        "language": ["ja"],
        "document_type": "pdf",
        "local_pdf": raw_relative_path,
        "raw_relative_path": raw_relative_path,
        "page_count": pdf_page_count(path),
        "file_size_bytes": stat.st_size,
        "checksum_sha256": sha256_file(path),
        "external_reference": "",
        "rights_notes": "",
        "inventory": {
            "inventoried_at": datetime.now(timezone.utc).isoformat(),
            "inventory_method": "scripts/inventory_sources.py",
        },
    }


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        records = json.load(handle)
    return {record["local_pdf"]: record for record in records if "local_pdf" in record}


def merge_record(existing: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return new

    merged = dict(existing)
    for key, value in new.items():
        if key == "inventory" and merged.get("inventory"):
            continue
        if key in {"repository", "call_number", "citation", "date", "external_reference", "rights_notes"}:
            if merged.get(key):
                continue
        merged[key] = value
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory raw PDFs into sources metadata.")
    parser.add_argument("--corpus-root", default=str(DEFAULT_CORPUS_ROOT))
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    corpus_root = Path(args.corpus_root)
    output_path = Path(args.output)
    if not corpus_root.exists():
        raise SystemExit(f"Corpus root does not exist: {corpus_root}")

    existing = load_existing(output_path)
    records = []
    for pdf_path in sorted(corpus_root.rglob("*")):
        if pdf_path.is_file() and pdf_path.suffix.lower() == ".pdf":
            new_record = metadata_for(pdf_path, corpus_root)
            records.append(merge_record(existing.get(new_record["local_pdf"]), new_record))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"Inventoried {len(records)} PDF source(s) into {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
