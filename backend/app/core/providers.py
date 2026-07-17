from __future__ import annotations

import base64
import csv
import io
import json
import os
import subprocess
import sys
import time
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import httpx

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BUNDLE_ROOT = Path(sys._MEIPASS)
else:
    BUNDLE_ROOT = Path(__file__).resolve().parents[3]

if getattr(sys, 'frozen', False):
    DATA_ROOT = Path(sys.executable).parent
else:
    DATA_ROOT = Path(__file__).resolve().parents[3]

NDLOCR_VENDOR_DIR = BUNDLE_ROOT / "tools" / "vendor" / "ndlocr-lite"
OCR_WORK_DIR = DATA_ROOT / "artifacts" / "ocr" / "work"

_LAST_OCR_TIME = 0.0
_CLEANER_TASK = None

async def _register_ocr_activity():
    global _LAST_OCR_TIME, _CLEANER_TASK
    _LAST_OCR_TIME = time.time()
    
    if _CLEANER_TASK is None or _CLEANER_TASK.done():
        _CLEANER_TASK = asyncio.create_task(_ocr_cache_cleaner_loop())

async def _ocr_cache_cleaner_loop():
    global _LAST_OCR_TIME
    while True:
        await asyncio.sleep(60)  # Check every minute
        idle_seconds = time.time() - _LAST_OCR_TIME
        if idle_seconds >= 300:  # 5 minutes
            try:
                from ocr import clear_ocr_model_cache
                clear_ocr_model_cache()
                print("[INFO] OCR cache cleared due to 5 minutes of inactivity.")
            except Exception as e:
                print(f"[WARNING] Failed to clear OCR cache: {e}")
            break  # Stop the loop until the next OCR activity registers it again


class BaseOCREngine(ABC):
    @property
    @abstractmethod
    def engine_id(self) -> str:
        """Unique identifier for this OCR engine."""
        pass

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable label for the engine."""
        pass

    @property
    def options_schema(self) -> List[Dict[str, Any]]:
        """Optional list of configuration parameters that the engine accepts."""
        return []


    @abstractmethod
    async def run_ocr(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Runs OCR on the given image crop and returns a dictionary with the transcription:
        {
            "text": "Transcribed text",
            "page_json": {
                "contents": [{"text": "line 1"}, {"text": "line 2"}]
            }
        }
        """
        pass

    async def run_table_parse(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any] | None:
        """Optionally parses the image crop directly into structured table rows.
        If returns None, the backend will fall back to its native line-split parsing of the OCR text.
        """
        return None


class NDLOCREngine(BaseOCREngine):
    @property
    def engine_id(self) -> str:
        return "ndlocr_lite"

    @property
    def label(self) -> str:
        return "NDLOCR-Lite (Local)"

    async def run_ocr(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
        source_id = settings.get("source_id", "unknown")
        page = settings.get("page", 1)
        region_id = settings.get("region_id", "region")

        ndlocr_src = NDLOCR_VENDOR_DIR / "src"
        if not ndlocr_src.exists():
            raise FileNotFoundError(f"NDLOCR-Lite is missing at {NDLOCR_VENDOR_DIR}")

        work_dir = OCR_WORK_DIR / "region-ocr" / source_id / f"page_{page:04d}" / region_id
        image_dir = work_dir / "images"
        output_dir = work_dir / "ndlocr-output"
        image_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        ocr_input_path = image_dir / "region.png"

        # Pillow image conversion (done synchronously since it is fast)
        from PIL import Image
        with Image.open(crop_path) as img:
            img.save(ocr_input_path)

        # Import process dynamically from ndlocr-lite
        if str(ndlocr_src) not in sys.path:
            sys.path.insert(0, str(ndlocr_src))
        from ocr import process as run_ocr_process

        import argparse
        args = argparse.Namespace(
            sourcedir=str(image_dir),
            sourceimg=None,
            output=str(output_dir),
            viz=False,
            det_weights=str(ndlocr_src / "model" / "deim-s-1024x1024.onnx"),
            det_classes=str(ndlocr_src / "config" / "ndl.yaml"),
            det_score_threshold=0.2,
            det_conf_threshold=0.25,
            det_iou_threshold=0.2,
            simple_mode=False,
            rec_weights30=str(ndlocr_src / "model" / "parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx"),
            rec_weights50=str(ndlocr_src / "model" / "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"),
            rec_weights=str(ndlocr_src / "model" / "parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx"),
            rec_classes=str(ndlocr_src / "config" / "NDLmoji.yaml"),
            device="cpu",
            enable_tcy=False,
            json_only=True
        )

        # Record activity and run in thread
        await _register_ocr_activity()
        try:
            await asyncio.to_thread(run_ocr_process, args)
        except Exception as exc:
            raise RuntimeError(f"NDLOCR-Lite failed: {exc}") from exc

        expected = output_dir / "region.json"
        if expected.exists():
            json_path = expected
        else:
            outputs = sorted(output_dir.glob("*.json"))
            if outputs:
                json_path = outputs[0]
            else:
                raise FileNotFoundError("NDLOCR-Lite did not produce JSON output")

        with json_path.open("r", encoding="utf-8") as f:
            page_json = json.load(f)

        # Flatten the text lines
        lines: List[str] = []
        for block in page_json.get("contents", []):
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
            elif isinstance(block, list):
                for item in block:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            lines.append(text.strip())
        text_content = "\n".join(lines)

        return {
            "text": text_content,
            "page_json": page_json
        }


class VisionLLMOCREngine(BaseOCREngine):
    def __init__(self, provider: str, api_key: str, model_name: str | None = None):
        self._provider = provider
        self.api_key = api_key
        self._model_name = model_name

    @property
    def engine_id(self) -> str:
        return f"vision_llm_{self._provider}"

    @property
    def label(self) -> str:
        prov_labels = {
            "gemini": "Google Gemini API",
            "openai": "OpenAI GPT-4o",
            "anthropic": "Anthropic Claude API"
        }
        return prov_labels.get(self._provider, f"Vision LLM ({self._provider})")

    @property
    def model_name(self) -> str:
        if self._model_name:
            return self._model_name
        defaults = {
            "gemini": "gemini-2.5-flash",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-sonnet-20241022"
        }
        return defaults.get(self._provider, "unknown")

    async def run_ocr(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
        base64_image = self._encode_image(crop_path)
        prompt = (
            "You are a professional transcriber for modern and historical Japanese archival materials. "
            "Transcribe all text visible in this cropped page image. Preserve the exact layout and line breaks. "
            "Do not translate. Do not add any greetings, preamble, notes, or markdown code blocks (e.g. do not wrap in triple backticks). "
            "Just output the transcribed Japanese text."
        )

        text = await self._call_vision_api(base64_image, prompt)
        
        # Build standard compatible NDL-OCR format contents
        contents = []
        for line in text.splitlines():
            cleaned = line.strip()
            if cleaned:
                contents.append({"text": cleaned})

        return {
            "text": text,
            "page_json": {
                "contents": contents
            }
        }

    async def run_table_parse(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any] | None:
        base64_image = self._encode_image(crop_path)
        prompt = (
            "You are a professional data extraction agent. Convert the table visible in this cropped page image "
            "into a clean, comma-separated values (CSV) format. Ensure that:\n"
            "1. You output only the CSV data.\n"
            "2. Do not add any preamble, conversational text, notes, or explanations.\n"
            "3. Do not wrap the CSV in markdown code blocks.\n"
            "4. Preserve column headers and cell values exactly as written.\n"
            "5. If a cell is blank, leave it empty."
        )

        csv_text = await self._call_vision_api(base64_image, prompt)
        csv_text = self._clean_llm_markdown_block(csv_text)

        # Parse CSV into structured rows and columns
        rows = []
        columns = []
        try:
            reader = csv.reader(io.StringIO(csv_text.strip()))
            parsed_rows = list(reader)
            if parsed_rows:
                # Deduce columns from the first row or max column length
                col_count = max(len(r) for r in parsed_rows)
                columns = [
                    {
                        "column_id": f"col_{index:03d}",
                        "label": parsed_rows[0][index-1] if len(parsed_rows[0]) >= index else f"Column {index}",
                        "review_status": "needs_review",
                    }
                    for index in range(1, col_count + 1)
                ]

                # We skip the headers row if we treat them as columns, otherwise keep it if needed.
                # Let's keep headers as col labels but populate rows from row 1 onward (or row 0 if no clear headers)
                # To be conservative, parse all rows as cells.
                for row_index, row in enumerate(parsed_rows, start=1):
                    rows.append(
                        {
                            "row_id": f"row_{row_index:03d}",
                            "cells": [
                                {
                                    "column_id": f"col_{column_index:03d}",
                                    "text": cell.strip(),
                                    "review_status": "needs_review",
                                }
                                for column_index, cell in enumerate(row, start=1)
                            ],
                            "source_line": ",".join(row),
                            "review_status": "needs_review",
                        }
                    )
        except Exception as e:
            # Fallback to line split if CSV parsing fails
            return None

        # Build drafts
        # Helper conversions similar to original table logic
        from backend.app.main import table_rows_to_markdown, table_rows_to_csv
        markdown_draft = table_rows_to_markdown(rows)
        csv_draft = table_rows_to_csv(rows)

        return {
            "flat_ocr_text": csv_text,
            "markdown_draft": markdown_draft,
            "csv_draft": csv_draft,
            "rows": rows,
            "columns": columns,
            "parser": {
                "engine": f"llm_vision_table_{self._provider}",
                "requested_engine": self.engine_id,
                "method": f"Direct table layout extraction via {self.model_name}.",
                "status": "needs_review",
            }
        }

    def _encode_image(self, image_path: Path) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _clean_llm_markdown_block(self, text: str) -> str:
        text = text.strip()
        # Remove ```csv ... ``` wrapper if the model outputted it despite prompt instructions
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    async def _call_vision_api(self, base64_image: str, prompt: str) -> str:
        async with httpx.AsyncClient() as client:
            if self._provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64_image
                                    }
                                }
                            ]
                        }
                    ]
                }
                response = await client.post(url, json=payload, timeout=60.0)
                if response.status_code != 200:
                    raise RuntimeError(f"Gemini API error ({response.status_code}): {response.text}")
                
                res_data = response.json()
                try:
                    return res_data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    raise RuntimeError(f"Unexpected response format from Gemini API: {res_data}")

            elif self._provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    "max_tokens": 4096
                }
                response = await client.post(url, headers=headers, json=payload, timeout=60.0)
                if response.status_code != 200:
                    raise RuntimeError(f"OpenAI API error ({response.status_code}): {response.text}")
                
                res_data = response.json()
                try:
                    return res_data["choices"][0]["message"]["content"]
                except (KeyError, IndexError):
                    raise RuntimeError(f"Unexpected response format from OpenAI API: {res_data}")

            elif self._provider == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.model_name,
                    "max_tokens": 4096,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": base64_image
                                    }
                                },
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ]
                }
                response = await client.post(url, headers=headers, json=payload, timeout=60.0)
                if response.status_code != 200:
                    raise RuntimeError(f"Anthropic API error ({response.status_code}): {response.text}")
                
                res_data = response.json()
                try:
                    return res_data["content"][0]["text"]
                except (KeyError, IndexError):
                    raise RuntimeError(f"Unexpected response format from Anthropic API: {res_data}")

            else:
                raise ValueError(f"Unknown API provider: {self._provider}")
class MineruOCREngine(BaseOCREngine):
    def __init__(self, api_key: str, api_url: str = "https://mineru.net", model_version: str = "vlm"):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model_version = model_version

    @property
    def engine_id(self) -> str:
        return "mineru"

    @property
    def label(self) -> str:
        return f"MinerU Cloud API ({self.model_version})"

    @property
    def options_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "language",
                "label": "Language",
                "type": "select",
                "default": "ch",
                "choices": [
                    {"value": "ch", "label": "Chinese/English"},
                    {"value": "japan", "label": "Japanese"},
                    {"value": "en", "label": "English"},
                    {"value": "korean", "label": "Korean"},
                    {"value": "latin", "label": "Latin Languages"}
                ]
            },
            {
                "name": "model_version",
                "label": "Model",
                "type": "select",
                "default": "vlm",
                "choices": [
                    {"value": "vlm", "label": "VLM"},
                    {"value": "pipeline", "label": "Pipeline"}
                ]
            },
            {
                "name": "enable_table",
                "label": "Tables",
                "type": "boolean",
                "default": True
            },
            {
                "name": "enable_formula",
                "label": "Formulas",
                "type": "boolean",
                "default": True
            }
        ]

    async def run_ocr(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
        filename = crop_path.name
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            batch_url = f"{self.api_url}/api/v4/file-urls/batch"
            payload = {
                "files": [
                    {"name": filename, "data_id": settings.get("region_id", "region")}
                ],
                "model_version": settings.get("model_version") or self.model_version
            }
            if settings.get("language"):
                payload["language"] = settings["language"]
            if settings.get("enable_table") is not None:
                payload["enable_table"] = settings["enable_table"]
            if settings.get("enable_formula") is not None:
                payload["enable_formula"] = settings["enable_formula"]
            
            try:
                resp = await client.post(batch_url, headers=headers, json=payload, timeout=60.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru API batch creation timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru API batch creation request failed: {exc}") from exc

            if resp.status_code != 200:
                raise RuntimeError(f"Mineru API batch error ({resp.status_code}): {resp.text}")
            
            res_json = resp.json()
            if res_json.get("code") != 0:
                raise RuntimeError(f"Mineru API batch error: {res_json.get('msg')}")
            
            data = res_json.get("data", {})
            batch_id = data.get("batch_id")
            file_urls = data.get("file_urls", [])
            if not batch_id or not file_urls:
                raise RuntimeError(f"Mineru API returned invalid data: {res_json}")
                
            upload_url = file_urls[0]
            
            file_bytes = crop_path.read_bytes()
            try:
                upload_resp = await client.put(upload_url, content=file_bytes, timeout=300.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru file upload timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru file upload request failed: {exc}") from exc

            if upload_resp.status_code != 200:
                raise RuntimeError(f"Mineru file upload failed ({upload_resp.status_code}): {upload_resp.text}")
                    
            import asyncio
            import zipfile
            
            results_url = f"{self.api_url}/api/v4/extract-results/batch/{batch_id}"
            max_attempts = 60
            attempt = 0
            full_zip_url = None
            
            while attempt < max_attempts:
                await asyncio.sleep(2.0)
                attempt += 1
                
                try:
                    resp = await client.get(results_url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=60.0)
                except httpx.TimeoutException:
                    continue
                except httpx.HTTPError:
                    continue

                if resp.status_code != 200:
                    continue
                    
                res_json = resp.json()
                if res_json.get("code") != 0:
                    raise RuntimeError(f"Mineru API status error: {res_json.get('msg')}")
                
                data = res_json.get("data", {})
                extract_results = data.get("extract_result", [])
                if not extract_results:
                    continue
                
                result = extract_results[0]
                state = result.get("state")
                
                if state == "done":
                    full_zip_url = result.get("full_zip_url")
                    break
                elif state == "failed":
                    err_msg = result.get("err_msg", "Unknown parsing failure")
                    raise RuntimeError(f"Mineru parsing task failed: {err_msg}")
                    
            if not full_zip_url:
                raise TimeoutError("Mineru parsing timed out.")
                
            try:
                zip_resp = await client.get(full_zip_url, timeout=180.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru ZIP download timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru ZIP download request failed: {exc}") from exc

            if zip_resp.status_code != 200:
                raise RuntimeError(f"Failed to download Mineru result zip: {zip_resp.text}")

                
            text = ""
            content_json = None
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                zip_filenames = z.namelist()
                print(f"Mineru ZIP contents: {zip_filenames}")
                
                for name in zip_filenames:
                    if name.endswith("full.md") or name.endswith("/full.md"):
                        text = z.read(name).decode("utf-8")
                        break
                        
                content_file_name = None
                for name in zip_filenames:
                    if "content_list.json" in name:
                        content_file_name = name
                        break
                if not content_file_name:
                    for name in zip_filenames:
                        if "middle.json" in name:
                            content_file_name = name
                            break
                if not content_file_name:
                    for name in zip_filenames:
                        if name.endswith(".json") and "model.json" not in name:
                            content_file_name = name
                            break
                            
                if content_file_name:
                    try:
                        raw_data = json.loads(z.read(content_file_name).decode("utf-8"))
                        if isinstance(raw_data, list):
                            content_json = raw_data
                        elif isinstance(raw_data, dict):
                            if "content_list" in raw_data and isinstance(raw_data["content_list"], list):
                                content_json = raw_data["content_list"]
                            elif "pdf_info" in raw_data and isinstance(raw_data["pdf_info"], list):
                                blocks = []
                                for page_data in raw_data["pdf_info"]:
                                    if isinstance(page_data, dict) and "para_blocks" in page_data:
                                        pblocks = page_data["para_blocks"]
                                        if isinstance(pblocks, list):
                                            blocks.extend(pblocks)
                                content_json = blocks
                            else:
                                for k, v in raw_data.items():
                                    if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict) and ("type" in v[0] or "bbox" in v[0]):
                                        content_json = v
                                        break
                    except Exception as e:
                        print(f"Failed to parse Mineru content JSON from {content_file_name}: {e}")
                        
            contents = []
            text_content = ""
            
            if content_json and isinstance(content_json, list):
                lines = []
                for item in content_json:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type", "")
                    
                    # If it's a text block with individual lines, parse line-by-line
                    if item_type == "text" and "lines" in item and isinstance(item["lines"], list):
                        for line in item["lines"]:
                            if not isinstance(line, dict):
                                continue
                            line_text = line.get("text", "") or line.get("content", "")
                            if not line_text and "spans" in line and isinstance(line["spans"], list):
                                span_texts = []
                                for span in line["spans"]:
                                    if isinstance(span, dict):
                                        s_text = span.get("content", "") or span.get("text", "")
                                        if s_text:
                                            span_texts.append(str(s_text))
                                line_text = "".join(span_texts)
                            
                            line_text = str(line_text).strip()
                            if not line_text:
                                continue
                                
                            lines.append(line_text)
                            line_dict = {
                                "text": line_text,
                                "isTextline": "true"
                            }
                            
                            # Get bounding box for this line
                            line_bbox = line.get("bbox")
                            if not line_bbox and "spans" in line and isinstance(line["spans"], list) and len(line["spans"]) > 0:
                                first_span = line["spans"][0]
                                if isinstance(first_span, dict):
                                    line_bbox = first_span.get("bbox")
                            if not line_bbox:
                                line_bbox = item.get("bbox")
                                
                            if line_bbox and isinstance(line_bbox, list) and len(line_bbox) >= 4:
                                try:
                                    x_min, y_min, x_max, y_max = float(line_bbox[0]), float(line_bbox[1]), float(line_bbox[2]), float(line_bbox[3])
                                    line_dict["boundingBox"] = [
                                        [x_min, y_min],
                                        [x_min, y_max],
                                        [x_max, y_min],
                                        [x_max, y_max]
                                    ]
                                except ValueError:
                                    pass
                            contents.append(line_dict)
                    else:
                        item_text = item.get("text", "") or item.get("markdown", "") or item.get("html", "")
                        
                        # Try parsing from nested structure if direct text not found
                        if not item_text:
                            nested_texts = []
                            if "lines" in item and isinstance(item["lines"], list):
                                for line in item["lines"]:
                                    if isinstance(line, dict):
                                        line_text = line.get("text", "") or line.get("content", "")
                                        if not line_text and "spans" in line and isinstance(line["spans"], list):
                                            span_texts = []
                                            for span in line["spans"]:
                                                if isinstance(span, dict):
                                                    s_text = span.get("content", "") or span.get("text", "")
                                                    if s_text:
                                                        span_texts.append(str(s_text))
                                            line_text = "".join(span_texts)
                                        if line_text:
                                            nested_texts.append(str(line_text))
                            elif "blocks" in item and isinstance(item["blocks"], list):
                                for sub_block in item["blocks"]:
                                    if isinstance(sub_block, dict):
                                        sb_text = sub_block.get("text", "") or sub_block.get("markdown", "") or sub_block.get("html", "")
                                        if sb_text:
                                            nested_texts.append(str(sb_text))
                            if nested_texts:
                                item_text = "\n".join(nested_texts).strip()
                                
                        if not item_text:
                            if item_type == "table":
                                item_text = "[Table]"
                            elif item_type == "equation":
                                item_text = item.get("latex", "[Equation]")
                            elif item_type == "image":
                                item_text = "[Image]"
                                
                        item_text = str(item_text).strip()
                        if not item_text:
                            continue
                            
                        lines.append(item_text)
                        block_dict = {
                            "text": item_text,
                            "isTextline": "true"
                        }
                        
                        bbox = item.get("bbox")
                        if bbox and isinstance(bbox, list) and len(bbox) >= 4:
                            try:
                                x_min, y_min, x_max, y_max = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                                block_dict["boundingBox"] = [
                                    [x_min, y_min],
                                    [x_min, y_max],
                                    [x_max, y_min],
                                    [x_max, y_max]
                                ]
                            except ValueError:
                                pass
                        contents.append(block_dict)
                text_content = "\n".join(lines)
            else:
                text_content = text
                for line in text.splitlines():
                    cleaned = line.strip()
                    if cleaned:
                        contents.append({"text": cleaned})
                    
            return {
                "text": text_content,
                "page_json": {
                    "contents": contents,
                    "imginfo": {
                        "img_width": 1000,
                        "img_height": 1000
                    }
                }
            }

    def _compress_and_chunk_pdf(self, pdf_path: Path, temp_dir: Path, chunk_size: int = 10) -> list[tuple[Path, list[int]]]:
        import pypdfium2 as pdfium
        from PIL import Image

        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
        except Exception as exc:
            raise RuntimeError(f"Failed to open PDF for chunking: {exc}") from exc

        total_pages = len(pdf)
        chunks = []
        
        for start_idx in range(0, total_pages, chunk_size):
            end_idx = min(start_idx + chunk_size, total_pages)
            page_numbers = list(range(start_idx + 1, end_idx + 1))
            
            images = []
            for idx in range(start_idx, end_idx):
                try:
                    bitmap = pdf[idx].render(scale=1.5)
                    pil_img = bitmap.to_pil()
                    gray_img = pil_img.convert("L")
                    images.append(gray_img)
                except Exception as exc:
                    print(f"Warning: Failed to render page {idx + 1} for chunking: {exc}")

            if images:
                chunk_path = temp_dir / f"chunk_{start_idx + 1}_to_{end_idx}.pdf"
                images[0].save(
                    chunk_path,
                    save_all=True,
                    append_images=images[1:],
                    resolution=150.0,
                    quality=70
                )
                chunks.append((chunk_path, page_numbers))
                
        pdf.close()
        return chunks

    async def _run_ocr_pdf_single_chunk(self, client: httpx.AsyncClient, pdf_path: Path, settings: Dict[str, Any], progress_callback=None) -> Dict[int, Dict[str, Any]]:
        return await self.run_ocr_pdf_original(pdf_path, settings, progress_callback)

    async def run_ocr_pdf(self, pdf_path: Path, settings: Dict[str, Any], progress_callback=None) -> Dict[int, Dict[str, Any]]:
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
            num_pages = len(pdf)
            pdf.close()
        except Exception:
            num_pages = 1

        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        should_chunk = (file_size_mb > 10.0 or num_pages > 5)

        if not should_chunk:
            return await self.run_ocr_pdf_original(pdf_path, settings, progress_callback)

        import tempfile
        pages_data = {}
        
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            temp_dir = Path(tmp_dir_str)
            msg = f"Large PDF detected ({file_size_mb:.1f} MB, {num_pages} pages). Compressing & chunking..."
            print(f"[MinerU Cloud API] {msg}")
            if progress_callback:
                await progress_callback(msg)

            chunks = self._compress_and_chunk_pdf(pdf_path, temp_dir, chunk_size=10)
            
            async with httpx.AsyncClient() as client:
                for chunk_idx, (chunk_path, page_numbers) in enumerate(chunks, 1):
                    msg = f"Processing chunk {chunk_idx}/{len(chunks)} (pages {page_numbers[0]}-{page_numbers[-1]})..."
                    print(f"[MinerU Cloud API] {msg}")
                    if progress_callback:
                        await progress_callback(msg)
                    
                    try:
                        chunk_results = await self._run_ocr_pdf_single_chunk(client, chunk_path, settings, progress_callback)
                        for chunk_p, p_data in chunk_results.items():
                            if 1 <= chunk_p <= len(page_numbers):
                                orig_page = page_numbers[chunk_p - 1]
                                pages_data[orig_page] = p_data
                    except Exception as e:
                        print(f"Error processing chunk {chunk_idx}: {e}")
                        continue

        return pages_data

    async def run_ocr_pdf_original(self, pdf_path: Path, settings: Dict[str, Any], progress_callback=None) -> Dict[int, Dict[str, Any]]:
        filename = pdf_path.name
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            batch_url = f"{self.api_url}/api/v4/file-urls/batch"
            payload = {
                "files": [
                    {"name": filename, "data_id": settings.get("region_id", "region")}
                ],
                "model_version": settings.get("model_version") or self.model_version
            }
            if settings.get("language"):
                payload["language"] = settings["language"]
            if settings.get("enable_table") is not None:
                payload["enable_table"] = settings["enable_table"]
            if settings.get("enable_formula") is not None:
                payload["enable_formula"] = settings["enable_formula"]
            
            try:
                resp = await client.post(batch_url, headers=headers, json=payload, timeout=60.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru API batch creation timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru API batch creation request failed: {exc}") from exc

            if resp.status_code != 200:
                raise RuntimeError(f"Mineru API batch error ({resp.status_code}): {resp.text}")
            
            res_json = resp.json()
            if res_json.get("code") != 0:
                raise RuntimeError(f"Mineru API batch error: {res_json.get('msg')}")
            
            data = res_json.get("data", {})
            batch_id = data.get("batch_id")
            file_urls = data.get("file_urls", [])
            if not batch_id or not file_urls:
                raise RuntimeError(f"Mineru API returned invalid data: {res_json}")
                
            upload_url = file_urls[0]
            
            if progress_callback:
                await progress_callback("Uploading PDF to MinerU...")
                
            file_bytes = pdf_path.read_bytes()
            try:
                upload_resp = await client.put(upload_url, content=file_bytes, timeout=600.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru file upload timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru file upload request failed: {exc}") from exc

            if upload_resp.status_code != 200:
                raise RuntimeError(f"Mineru file upload failed ({upload_resp.status_code}): {upload_resp.text}")
                    
            import asyncio
            import zipfile
            
            results_url = f"{self.api_url}/api/v4/extract-results/batch/{batch_id}"
            max_attempts = 120
            attempt = 0
            full_zip_url = None
            
            while attempt < max_attempts:
                await asyncio.sleep(3.0)
                attempt += 1
                
                if progress_callback:
                    await progress_callback(f"Waiting for MinerU parsing... (attempt {attempt}/{max_attempts})")
                
                try:
                    resp = await client.get(results_url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=60.0)
                except httpx.TimeoutException:
                    continue
                except httpx.HTTPError:
                    continue

                if resp.status_code != 200:
                    continue
                    
                res_json = resp.json()
                if res_json.get("code") != 0:
                    raise RuntimeError(f"Mineru API status error: {res_json.get('msg')}")
                
                data = res_json.get("data", {})
                extract_results = data.get("extract_result", [])
                if not extract_results:
                    continue
                
                result = extract_results[0]
                state = result.get("state")
                
                if state == "done":
                    full_zip_url = result.get("full_zip_url")
                    break
                elif state == "failed":
                    err_msg = result.get("err_msg", "Unknown parsing failure")
                    raise RuntimeError(f"Mineru parsing task failed: {err_msg}")
                    
            if not full_zip_url:
                raise TimeoutError("Mineru parsing timed out.")
                
            if progress_callback:
                await progress_callback("Downloading ZIP results...")
                
            try:
                zip_resp = await client.get(full_zip_url, timeout=300.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Mineru ZIP download timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Mineru ZIP download request failed: {exc}") from exc

            if zip_resp.status_code != 200:
                raise RuntimeError(f"Failed to download Mineru result zip: {zip_resp.text}")

            if progress_callback:
                await progress_callback("Extracting and parsing pages...")

            page_sizes = {}
            try:
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(str(pdf_path))
                for p_idx in range(len(pdf)):
                    page_sizes[p_idx + 1] = pdf[p_idx].get_size()
                pdf.close()
            except Exception as e:
                print(f"Warning: Failed to load PDF page sizes: {e}")

            pages_data = {}
            page_sizes_from_mineru = {}
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                zip_filenames = z.namelist()
                
                # Try to extract page sizes directly from MinerU's output JSONs (e.g. layout.json or model.json)
                for name in zip_filenames:
                    if name.endswith(".json"):
                        try:
                            raw_info = json.loads(z.read(name).decode("utf-8"))
                            if isinstance(raw_info, dict) and "pdf_info" in raw_info:
                                for page_entry in raw_info["pdf_info"]:
                                    if isinstance(page_entry, dict) and "page_idx" in page_entry:
                                        p_idx = page_entry["page_idx"]
                                        if "page_size" in page_entry:
                                            page_sizes_from_mineru[p_idx + 1] = page_entry["page_size"]
                        except Exception:
                            pass
                
                content_file_name = None
                for name in zip_filenames:
                    if "content_list.json" in name:
                        content_file_name = name
                        break
                if not content_file_name:
                    for name in zip_filenames:
                        if "middle.json" in name:
                            content_file_name = name
                            break
                if not content_file_name:
                    for name in zip_filenames:
                        if name.endswith(".json") and "model.json" not in name:
                            content_file_name = name
                            break
                            
                content_json = None
                raw_data = None
                if content_file_name:
                    try:
                        raw_data = json.loads(z.read(content_file_name).decode("utf-8"))
                    except Exception as e:
                        print(f"Failed to parse Mineru content JSON from {content_file_name}: {e}")
                
                items_by_page = {}
                
                if raw_data:
                    if isinstance(raw_data, list):
                        content_json = raw_data
                    elif isinstance(raw_data, dict):
                        if "content_list" in raw_data and isinstance(raw_data["content_list"], list):
                            content_json = raw_data["content_list"]
                        elif "pdf_info" in raw_data and isinstance(raw_data["pdf_info"], list):
                            for page_idx, page_data in enumerate(raw_data["pdf_info"]):
                                if isinstance(page_data, dict) and "para_blocks" in page_data:
                                    pblocks = page_data["para_blocks"]
                                    if isinstance(pblocks, list):
                                        items_by_page[page_idx] = pblocks
                
                if content_json and isinstance(content_json, list):
                    for item in content_json:
                        if not isinstance(item, dict):
                            continue
                        page_idx = item.get("page_idx")
                        if page_idx is None:
                            page_idx = item.get("page", 0)
                        try:
                            page_idx = int(page_idx)
                        except (ValueError, TypeError):
                            page_idx = 0
                        items_by_page.setdefault(page_idx, []).append(item)
                
                for page_idx, page_items in items_by_page.items():
                    page_number = page_idx + 1
                    lines = []
                    contents = []
                    table_counter = 0
                    page_tables = {}
                    for item in page_items:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get("type", "")
                        
                        if item_type == "text" and "lines" in item and isinstance(item["lines"], list):
                            for line in item["lines"]:
                                if not isinstance(line, dict):
                                    continue
                                line_text = line.get("text", "") or line.get("content", "")
                                if not line_text and "spans" in line and isinstance(line["spans"], list):
                                    span_texts = []
                                    for span in line["spans"]:
                                        if isinstance(span, dict):
                                            s_text = span.get("content", "") or span.get("text", "")
                                            if s_text:
                                                span_texts.append(str(s_text))
                                    line_text = "".join(span_texts)
                                
                                line_text = str(line_text).strip()
                                if not line_text:
                                    continue
                                    
                                lines.append(line_text)
                                line_dict = {
                                    "text": line_text,
                                    "isTextline": "true"
                                }
                                
                                line_bbox = line.get("bbox")
                                if not line_bbox and "spans" in line and isinstance(line["spans"], list) and len(line["spans"]) > 0:
                                    first_span = line["spans"][0]
                                    if isinstance(first_span, dict):
                                        line_bbox = first_span.get("bbox")
                                if not line_bbox:
                                    line_bbox = item.get("bbox")
                                    
                                if line_bbox and isinstance(line_bbox, list) and len(line_bbox) >= 4:
                                    try:
                                        x_min, y_min, x_max, y_max = float(line_bbox[0]), float(line_bbox[1]), float(line_bbox[2]), float(line_bbox[3])
                                        line_dict["boundingBox"] = [
                                            [x_min, y_min],
                                            [x_min, y_max],
                                            [x_max, y_min],
                                            [x_max, y_max]
                                        ]
                                    except ValueError:
                                        pass
                                contents.append(line_dict)
                        else:
                            if item_type == "table":
                                table_id = f"table_{table_counter}"
                                table_counter += 1
                                table_val = item.get("markdown", "") or item.get("text", "") or item.get("html", "")
                                if not table_val or not isinstance(table_val, str) or not table_val.strip():
                                    table_val = "| Column 1 | Column 2 |\n|---|---|\n| Cell 1 | Cell 2 |"
                                page_tables[table_id] = {
                                    "markdown": table_val.strip()
                                }
                                item_text = f"[Table: {table_id}]"
                            else:
                                item_text = item.get("text", "") or item.get("markdown", "") or item.get("html", "")
                            if not item_text:
                                nested_texts = []
                                if "lines" in item and isinstance(item["lines"], list):
                                    for line in item["lines"]:
                                        if isinstance(line, dict):
                                            line_text = line.get("text", "") or line.get("content", "")
                                            if not line_text and "spans" in line and isinstance(line["spans"], list):
                                                span_texts = []
                                                for span in line["spans"]:
                                                    if isinstance(span, dict):
                                                        s_text = span.get("content", "") or span.get("text", "")
                                                        if s_text:
                                                            span_texts.append(str(s_text))
                                                line_text = "".join(span_texts)
                                            if line_text:
                                                nested_texts.append(str(line_text))
                                elif "blocks" in item and isinstance(item["blocks"], list):
                                    for sub_block in item["blocks"]:
                                        if isinstance(sub_block, dict):
                                            sb_text = sub_block.get("text", "") or sub_block.get("markdown", "") or sub_block.get("html", "")
                                            if sb_text:
                                                nested_texts.append(str(sb_text))
                                if nested_texts:
                                    item_text = "\n".join(nested_texts).strip()
                                    
                            if not item_text:
                                if item_type == "table":
                                    item_text = "[Table]"
                                elif item_type == "equation":
                                    item_text = item.get("latex", "[Equation]")
                                elif item_type == "image":
                                    item_text = "[Image]"
                                    
                            item_text = str(item_text).strip()
                            if not item_text:
                                continue
                                
                            lines.append(item_text)
                            block_dict = {
                                "text": item_text,
                                "isTextline": "true"
                            }
                            
                            bbox = item.get("bbox")
                            if bbox and isinstance(bbox, list) and len(bbox) >= 4:
                                try:
                                    x_min, y_min, x_max, y_max = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                                    block_dict["boundingBox"] = [
                                        [x_min, y_min],
                                        [x_min, y_max],
                                        [x_max, y_min],
                                        [x_max, y_max]
                                    ]
                                except ValueError:
                                    pass
                            contents.append(block_dict)
                    
                    text_content = "\n".join(lines)
                    width, height = (1000.0, 1000.0)
                    if page_number in page_sizes_from_mineru:
                        width, height = page_sizes_from_mineru[page_number]
                    elif page_number in page_sizes:
                        width, height = page_sizes[page_number]
                        
                    pages_data[page_number] = {
                        "text": text_content,
                        "page_json": {
                            "contents": contents,
                            "imginfo": {
                                "img_width": width,
                                "img_height": height
                            },
                            "tables": page_tables
                        }
                    }
            
            return pages_data


class PaddleOCREngine(BaseOCREngine):
    def __init__(self, api_key: str, api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs", model: str = "PaddleOCR-VL-1.6"):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.model = model

    @property
    def engine_id(self) -> str:
        return "paddleocr"

    @property
    def label(self) -> str:
        return f"PaddleOCR API ({self.model})"

    @property
    def options_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "use_chart_recognition",
                "label": "Recognize Charts/Graphs",
                "type": "boolean",
                "default": False
            },
            {
                "name": "use_layout_detection",
                "label": "Enable Layout Detection",
                "type": "boolean",
                "default": True
            },
            {
                "name": "use_doc_orientation_classify",
                "label": "Document Orientation Classify",
                "type": "boolean",
                "default": False
            },
            {
                "name": "use_doc_unwarping",
                "label": "Document Unwarping",
                "type": "boolean",
                "default": False
            },
            {
                "name": "use_seal_recognition",
                "label": "Recognize Seals/Stamps",
                "type": "boolean",
                "default": False
            }
        ]

    async def run_ocr(self, crop_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"bearer {self.api_key}"
        }
        
        use_chart = settings.get("use_chart_recognition", False)
        use_layout = settings.get("use_layout_detection", True)
        use_orientation = settings.get("use_doc_orientation_classify", False)
        use_unwarping = settings.get("use_doc_unwarping", False)
        use_seal = settings.get("use_seal_recognition", False)

        data = {
            "model": self.model,
            "optionalPayload": json.dumps({
                "useDocOrientationClassify": use_orientation,
                "useDocUnwarping": use_unwarping,
                "useChartRecognition": use_chart,
                "useLayoutDetection": use_layout,
                "useSealRecognition": use_seal
            })
        }
        
        async with httpx.AsyncClient() as client:
            # 1. Submit OCR job
            file_bytes = crop_path.read_bytes()
            files = {
                "file": (crop_path.name, io.BytesIO(file_bytes), "image/png")
            }
            try:
                resp = await client.post(self.api_url, headers=headers, data=data, files=files, timeout=60.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"PaddleOCR API job submission timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"PaddleOCR API job submission request failed: {exc}") from exc

            if resp.status_code != 200:
                raise RuntimeError(f"PaddleOCR API job submission error ({resp.status_code}): {resp.text}")

            res_json = resp.json()
            job_data = res_json.get("data", {})
            job_id = job_data.get("jobId")
            if not job_id:
                raise RuntimeError(f"PaddleOCR API did not return a jobId: {res_json}")

            # 2. Poll OCR job status
            import asyncio
            job_status_url = f"{self.api_url}/{job_id}"
            max_attempts = 120  # 120 * 2s = 240s
            attempt = 0
            jsonl_url = None
            
            while attempt < max_attempts:
                await asyncio.sleep(2.0)
                attempt += 1
                
                try:
                    status_resp = await client.get(job_status_url, headers=headers, timeout=30.0)
                except (httpx.TimeoutException, httpx.HTTPError):
                    continue
                    
                if status_resp.status_code != 200:
                    continue
                    
                status_json = status_resp.json()
                status_data = status_json.get("data", {})
                state = status_data.get("state")
                
                if state == "done":
                    result_url = status_data.get("resultUrl", {})
                    jsonl_url = result_url.get("jsonUrl")
                    break
                elif state == "failed":
                    error_msg = status_data.get("errorMsg", "Unknown parsing failure")
                    raise RuntimeError(f"PaddleOCR parsing job failed: {error_msg}")
            
            if not jsonl_url:
                raise TimeoutError("PaddleOCR parsing task timed out.")

            # 3. Retrieve JSONL results
            try:
                jsonl_resp = await client.get(jsonl_url, timeout=60.0)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"PaddleOCR JSONL download timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"PaddleOCR JSONL download request failed: {exc}") from exc

            if jsonl_resp.status_code != 200:
                raise RuntimeError(f"Failed to download PaddleOCR result JSONL: {jsonl_resp.text}")

            # 4. Parse JSONL content
            markdown_texts = []
            for line in jsonl_resp.text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    line_data = json.loads(line)
                    result_data = line_data.get("result", {})
                    for res in result_data.get("layoutParsingResults", []):
                        if "markdown" in res and "text" in res["markdown"]:
                            markdown_texts.append(res["markdown"]["text"])
                except Exception:
                    pass

            text = "\n\n".join(markdown_texts)
            contents = []
            for line in text.splitlines():
                cleaned = line.strip()
                if cleaned:
                    contents.append({"text": cleaned})

            return {
                "text": text,
                "page_json": {
                    "contents": contents
                }
            }


async def asyncio_run_subprocess(command: List[str], cwd: str) -> subprocess.CompletedProcess:
    """Helper to run a command as an async subprocess to prevent blocking FastAPI thread."""
    import asyncio
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr
    )
