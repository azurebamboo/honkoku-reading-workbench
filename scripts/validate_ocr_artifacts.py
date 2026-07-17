#!/usr/bin/env python3
"""Validate tracked raw OCR manifests and page JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OCR_ROOTS = [
    ROOT / "artifacts" / "ocr" / "raw",
    ROOT / "artifacts" / "ocr" / "manual",
    ROOT / "artifacts" / "ocr" / "corrected",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_manifest(path: Path) -> list[str]:
    errors: list[str] = []
    manifest = load_json(path)
    for field in ("source_id", "source_path", "checksum_sha256", "pages", "page_json", "ocr_engine", "status"):
        if field not in manifest:
            errors.append(f"{path}: missing `{field}`")

    pages = manifest.get("pages", [])
    page_json = manifest.get("page_json", [])
    if len(pages) != len(page_json):
        errors.append(f"{path}: pages and page_json lengths differ")

    for relative_path in page_json:
        page_path = ROOT / relative_path
        if not page_path.exists():
            errors.append(f"{path}: missing page JSON {relative_path}")
            continue
        page_data = load_json(page_path)
        if not isinstance(page_data, dict):
            errors.append(f"{page_path}: page JSON must be an object")
            continue
        if "contents" not in page_data or "imginfo" not in page_data:
            errors.append(f"{page_path}: expected NDLOCR keys `contents` and `imginfo`")
    return errors


def main() -> int:
    manifests = []
    for root in OCR_ROOTS:
        manifests.extend(sorted(root.glob("*/manifest.json")))
    if not manifests:
        print("No tracked OCR manifests found.")
        return 1

    errors: list[str] = []
    for manifest_path in manifests:
        errors.extend(validate_manifest(manifest_path))

    if errors:
        print("OCR artifact validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    page_count = sum(len(load_json(path).get("page_json", [])) for path in manifests)
    print(f"Validated {len(manifests)} OCR manifest(s) and {page_count} page JSON file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
