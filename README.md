# Standalone OCR & Reading Desk Application

This is an extracted standalone version of the **Reading Desk** and **Batch OCR** functionalities from the Koshu Research Workbench. It operates locally and does not require an SQLite database setup to run its core OCR and proofreading workflows.

## Prerequisites

- **Python**: Version 3.10 or higher.
- **Node.js**: Version 18 or higher (with npm).

## Directory Structure

Place your local raw PDF files under `sources/raw/` (e.g. matching the structure defined in `sources/metadata/sources.json`).

OCR outputs will be written under:
- `artifacts/ocr/raw/` - Raw OCR results.
- `artifacts/ocr/corrected/` - Corrected and saved transcriptions.
- `artifacts/ocr/regions/` - Selected-region crops and OCR results.

## Quick Start (Easiest Way)

You can launch both the frontend and backend simultaneously using the provided startup script:

1. **Initialize Backend Environment (First time only)**:
   ```bash
   cd backend
   python -m venv .venv
   # Activate and install dependencies:
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate

   pip install -r requirements.txt
   cd ..
   ```

2. **Initialize Frontend Environment (First time only)**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

3. **Start the Application**:
   Run the startup script from the root directory:
   ```bash
   python scripts/start.py
   ```
   This will boot the FastAPI backend (port `8000`), spin up the Vite dev server (port `5173`), and automatically open the interface in your web browser. Press `Ctrl+C` in your terminal to cleanly terminate both servers.

## Running Separately

If you prefer to run the servers in separate terminals:

### Backend
```bash
cd backend
# Activate your venv, then:
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### Frontend
```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

## Configuring Cloud Vision OCR (Optional)

If you want to use cloud-based vision models (Gemini, GPT-4o, Claude) for OCR:
1. Copy `.env.example` in the root directory to `.env`.
2. Add your API keys:
   ```ini
   GEMINI_API_KEY=your-gemini-key
   OPENAI_API_KEY=your-openai-key
   ANTHROPIC_API_KEY=your-anthropic-key
   ```
3. Restart the backend server or start script.
