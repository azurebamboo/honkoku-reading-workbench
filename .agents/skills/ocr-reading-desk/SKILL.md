---
name: ocr-reading-desk
description: Local OCR, document proofreading, source management, and text/note organization workbench. Automatically installs dependencies, builds single-file web UI, launches backend on port 8000, opens browser, and provides CLI tools to import PDFs, merge OCR notes, and organize exports.
metadata:
  version: 1.0.0
---

# Standalone OCR & Reading Desk Skill

This skill turns the Standalone OCR & Reading Desk into an automated AI workbench. AI agents (Claude Code, Antigravity, CoWork, Cursor, OpenHands) can use this skill to boot the application, manage dependencies, control servers, import PDF/image sources, merge transcriptions, and organize exported notes.

---

## 1. Quick Start & Application Lifecycle

### Initial Setup / Bootstrapping
When the user asks to install or set up the OCR Reading Desk, or upon first time use:
```bash
python install.py
```
*or directly:*
```bash
python scripts/skill_launcher.py bootstrap
```
> **What this does**: Checks for Python 3.10+ and Node 18+, creates `.venv`, installs Python requirements (`pip install -r backend/requirements.txt`), installs npm packages, and builds the single-file React frontend bundle into `frontend/dist/index.html`.

### Launching the Application
When the user asks to *"launch OCR desk"*, *"open reading desk"*, or *"start the app"*:
```bash
python scripts/skill_launcher.py start
```
> **What this does**: Launches the FastAPI server on `http://127.0.0.1:8000/`, serves the React UI and API on port 8000, checks server health, and opens the default web browser.

### Checking Server Health
To verify if the server is already active:
```bash
python scripts/skill_launcher.py status
```

### Developer Mode (Instant Live Reload)
If the user wants to edit frontend source code with Hot Module Reloading (HMR):
```bash
python scripts/skill_launcher.py start --dev
```

---

## 2. Agent Action Tools (CLI Operations)

AI agents can perform high-level document and note workflows programmatically using built-in CLI helper tools:

### A. Importing PDF or Image Sources
To import scanned PDFs or image files into the workspace:
```bash
python scripts/agent_tools/import_source.py path/to/document.pdf --title "My Research Source"
```
* **Supported inputs**: `.pdf`, `.jpg`, `.png`, `.tiff`, `.webp`. Single images are automatically converted to PDF format and registered in `sources/metadata/sources.json`.

### B. Merging OCR Transcriptions & Notes
To combine raw or corrected OCR transcriptions across pages or multiple sources into a single clean Markdown note:
```bash
python scripts/agent_tools/merge_ocr_notes.py source_id_1 source_id_2 --output artifacts/notes/chapter_summary.md --title "Combined Chapter Summary"
```

### C. Searching & Listing Transcriptions
To view all available OCR source transcriptions:
```bash
python scripts/agent_tools/organize_exports.py list
```
To search for specific text or keywords across all OCR outputs:
```bash
python scripts/agent_tools/organize_exports.py search "keyword or phrase"
```

### D. Organizing & Exporting Projects
To group selected OCR source outputs into an export package:
```bash
python scripts/agent_tools/organize_exports.py export --name "Project_Alpha_Archive" --sources source_id_1 source_id_2
```

---

## 3. Guiding the User in the Web UI

When the web application opens at `http://127.0.0.1:8000/`:

1. **Reading Desk**:
   - Allows side-by-side viewing of original scanned PDF pages and OCR text transcriptions.
   - Users can edit, proofread, and save corrected text directly in the browser interface.
2. **Batch OCR**:
   - Users can trigger local NDL-OCR engine processing or cloud vision AI processing for entire PDF documents.
3. **Cloud AI Vision API Setup**:
   - If the user wants to run OCR using Gemini, GPT-4o, or Claude, remind them to copy `.env.example` to `.env` in the root directory and set their API keys:
     ```ini
     GEMINI_API_KEY=your-gemini-key
     OPENAI_API_KEY=your-openai-key
     ANTHROPIC_API_KEY=your-anthropic-key
     ```
