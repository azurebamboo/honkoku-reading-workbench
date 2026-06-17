from __future__ import annotations

import base64
import csv
import io
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[3]
NDLOCR_VENDOR_DIR = ROOT / "tools" / "vendor" / "ndlocr-lite"
OCR_WORK_DIR = ROOT / "artifacts" / "ocr" / "work"


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

        ocr_script = NDLOCR_VENDOR_DIR / "src" / "ocr.py"
        if not ocr_script.exists():
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

        command = [
            sys.executable,
            str(ocr_script),
            "--sourcedir",
            str(image_dir),
            "--output",
            str(output_dir),
            "--json-only",
        ]

        # Use an async subprocess run to keep FastAPI from blocking
        process = await asyncio_run_subprocess(command, cwd=str(NDLOCR_VENDOR_DIR / "src"))
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="ignore").strip()
            stdout = process.stdout.decode("utf-8", errors="ignore").strip()
            detail = stderr or stdout or "NDLOCR-Lite subprocess execution failed"
            raise RuntimeError(f"NDLOCR-Lite failed: {detail}")

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
