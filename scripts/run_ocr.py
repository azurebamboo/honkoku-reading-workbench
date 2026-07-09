#!/usr/bin/env python3
"""Run the supported NDLOCR pipeline for selected cataloged PDF pages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.core import NDLOCR_VENDOR_DIR
from backend.app.services.ocr_pipeline import full_pdf_pages, run_ocr_pages
from backend.app.services.source_ocr import source_by_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NDLOCR-Lite on selected PDF pages.")
    parser.add_argument("--source-id")
    parser.add_argument("--local-pdf")
    parser.add_argument("--pages", default="1-5")
    parser.add_argument("--all-pages", action="store_true", help="OCR the full PDF page range from diagnostics/metadata.")
    parser.add_argument("--missing-only", action="store_true", help="Skip pages that already exist in durable raw OCR.")
    parser.add_argument("--vendor-dir", default=str(NDLOCR_VENDOR_DIR))
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--enable-tcy", action="store_true")
    parser.add_argument("--keep-text", action="store_true")
    args = parser.parse_args()

    selected_pages = None
    if args.all_pages:
        if not args.source_id:
            parser.error("--all-pages requires --source-id")
        selected_pages = full_pdf_pages(source_by_id(args.source_id))

    result = run_ocr_pages(
        source_id=args.source_id,
        local_pdf=args.local_pdf,
        page_range=args.pages,
        pages=selected_pages,
        missing_only=args.missing_only,
        vendor_dir=Path(args.vendor_dir),
        scale=args.scale,
        enable_tcy=args.enable_tcy,
        keep_text=args.keep_text,
    )
    print(f"Wrote OCR manifest: {result['manifest_path']}")
    print(f"Processed {len(result['processed_pages'])} page(s); skipped {len(result['skipped_pages'])} existing page(s).")
    print(f"Manifest now tracks {len(result['page_json'])} page JSON file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
