# 📖 Standalone OCR & Reading Desk

A local-first, privacy-focused OCR, document proofreading, and transcription workbench designed for historical documents, scanned books, newspapers, and archival materials.

It operates entirely locally on your computer without requiring complex database setups or mandatory internet connectivity for core workflows.

---

## 📸 Screenshots

### 1. Interactive Reading Desk
Side-by-side view of original scanned pages and editable transcriptions, complete with bounding box overlays, line sync, region cropping, and live find-and-replace:

![Reading Desk Interface](docs/images/01_reading_desk_interface.png)

### 2. Batch Document OCR Processing
Automated multi-page document OCR queue with real-time progress tracking:

![Batch Review Interface](docs/images/02_batch_review_interface.png)

---

## ✨ Key Features

- **Side-by-Side Reading Desk**: Inspect original scanned PDF pages or images directly alongside editable transcriptions.
- **OCR Bounding Box Synchronization**: View OCR bounding boxes overlaid onto the scanned image. Clicking any box immediately highlights and navigates to the corresponding line in the text editor.
- **Precision Crop & Regional OCR**: Click and drag to select any column, headline, passage, or table. Export selections directly as image files or trigger regional OCR on specific sections.
- **Local & Offline by Default**: Powered by **NDL-OCR (NDLOCR-Lite)** developed by Japan's National Diet Library. Works 100% offline with zero subscription fees.
- **Optional Cloud AI, PaddleOCR & MinerU**: Easily connect Google Gemini, OpenAI GPT-4o, Anthropic Claude, Baidu AI Studio PaddleOCR, or MinerU API for alternative recognition passes, complex document layouts, or multilingual document parsing.
- **Browser Drag-and-Drop Import**: Drag PDFs, single images, or multi-image sets (`.pdf`, `.png`, `.jpg`, `.tiff`, `.webp`) directly into your browser window to import them instantly.
- **Full Proofreading Toolkit**: Integrated regex search & replace, undo/redo history, highlight tagging, and one-click transcription saving.
- **Batch Processing**: Run automated multi-page OCR across entire documents with real-time progress indicators.
- **Multi-Format Export**: Export verified transcriptions as plain text (`.txt`), formatted Markdown (`.md`), or structured JSON (`.json`).

---

## 🚀 Quick Start Guide

### Option 1: Standalone Download (Recommended for Most Users)
> **No Python, Node.js, or terminal commands required!** Everything (the local NDL-OCR engine, runtime, and web interface) is fully self-contained in the release package.

1. Go to the [**Latest GitHub Release (v1.0.6)**](https://github.com/azurebamboo/koshu-reading-workbench/releases/latest).
2. Download the zip file for your system:
   - **Windows**: [`koshu-workbench-windows.zip`](https://github.com/azurebamboo/koshu-reading-workbench/releases/latest/download/koshu-workbench-windows.zip)
   - **macOS**: [`koshu-workbench-macos.zip`](https://github.com/azurebamboo/koshu-reading-workbench/releases/latest/download/koshu-workbench-macos.zip)
3. Extract (unzip) the folder anywhere on your computer.
4. Launch the application:
   - **Windows**: Double-click **`start.bat`**
   - **macOS**: Double-click **`start.command`**
5. Your browser will automatically open to `http://localhost:8000/`. You are ready to start reading and proofreading!

---

### Option 2: Use with an AI Agent (Zero Manual Setup)
> **Zero manual setup!** This repository includes an official **AI Agent Skill** ([`SKILL.md`](SKILL.md) / [`.agents/skills/ocr-reading-desk/`](.agents/skills/ocr-reading-desk/)).

If you use an AI coding assistant (such as **Google Antigravity**, **Claude Code**, **Cursor**, or **OpenHands**):

1. Give your AI agent this repository URL or clone it into your workspace:
   ```text
   https://github.com/azurebamboo/koshu-reading-workbench
   ```
2. Simply ask your agent in natural language:
   - *"Install and start the OCR Reading Desk"*
   - *"Launch the reading desk and open my browser"*
   - *"Import this document: path/to/scan.pdf"*
   - *"Combine the notes for source 1 and source 2 into a chapter summary"*

Your agent will read [`SKILL.md`](SKILL.md), run the automated installer (`python install.py`), verify server health, launch the application on port `8000`, and manage document transcriptions via the built-in CLI tools.

---

### Option 3: Run from Source (For Developers & Power Users)
If you prefer to clone the Git repository and run directly from source:

1. **Prerequisites**:
   - **Python**: Version 3.10 or higher ([Download Python](https://www.python.org/downloads/))
   - **Node.js**: Version 18 or higher ([Download Node.js](https://nodejs.org/))

2. **One-Click Setup**:
   In your terminal inside the cloned project directory, run:
   ```bash
   python install.py
   ```
   > **What this does**: Automatically sets up the Python virtual environment, installs backend dependencies, installs frontend packages, and compiles the single-file web application bundle.

3. **Launch the Application**:
   - Double-click **`start.bat`** (Windows) / **`start.command`** (macOS), or run:
     ```bash
     python scripts/skill_launcher.py start
     ```

---

## 💡 How to Use the Reading Desk

1. **Import Documents**:
   - Click **Import File(s)** in the toolbar or simply drag and drop your PDF or image files anywhere onto the window.
2. **Select & Inspect**:
   - Choose your document and page from the top dropdown menus.
   - Click the **Boxes** button to toggle OCR bounding boxes on and off.
   - Click any bounding box on the image to locate and highlight that text in the editor.
3. **Crop & Regional OCR**:
   - Select **Crop** mode in the toolbar.
   - Drag a box over any passage, article, or table.
   - Click **Run Regional OCR** to extract text from that specific area, or **Export Page Crop** to download it as an image.
   - To clear a selection, click the **Clear Selection** button, press <kbd>Esc</kbd>, or click anywhere on the page.
4. **Proofread & Save**:
   - Edit and correct the transcription in the right-hand text editor.
   - Click **Save OCR Edit** (or press <kbd>Ctrl</kbd>+<kbd>S</kbd>) to save your corrected text.
5. **Export Your Work**:
   - Use **Export All TXT**, **Export All MD**, or **Export All JSON** to export clean transcripts of the entire document.

---

## 🤖 AI Agent Tools & Automation

In addition to the browser interface, AI agents (and automated terminal scripts) can perform document workflows programmatically using built-in CLI tools:

- **Automated Lifecycle Control**:
  ```bash
  python scripts/skill_launcher.py bootstrap   # Check requirements, set up .venv, install npm & build UI
  python scripts/skill_launcher.py start       # Launch backend server on port 8000 & open browser
  python scripts/skill_launcher.py status      # Check if server is running and healthy
  ```
- **Import Documents Programmatically**:
  ```bash
  python scripts/agent_tools/import_source.py path/to/document.pdf --title "Archival Source Title"
  ```
  *(Automatically converts `.pdf`, `.jpg`, `.png`, `.tiff`, and `.webp` images into registered sources)*
- **Merge & Synthesize Notes Across Sources**:
  ```bash
  python scripts/agent_tools/merge_ocr_notes.py source_1 source_2 --output artifacts/notes/summary.md --title "Combined Chapter Notes"
  ```
- **Search & Organize Transcriptions**:
  ```bash
  python scripts/agent_tools/organize_exports.py search "keyword or phrase"
  python scripts/agent_tools/organize_exports.py export --name "Project_Archive" --sources source_1 source_2
  ```

---

## 🌐 Optional: Cloud AI Vision, PaddleOCR, and MinerU APIs

While the workbench comes pre-configured with **NDL-OCR** for 100% offline local usage, you can also connect external cloud vision AI models and specialized online OCR services (**PaddleOCR**, **MinerU**) for complex layouts, formulas, or multilingual materials.

### What is an API Key & How to Get One
Online AI and OCR providers require an **API Key** (a private access token) to identify your account and authenticate requests. If you don't already have keys, you can register directly on each provider's website:

| Provider / Model | What It's Good For | How to Get an API Key |
| :--- | :--- | :--- |
| **Google Gemini** (`gemini-2.5-flash`) | Fast, multilingual vision & historical text understanding | Go to [Google AI Studio](https://aistudio.google.com/), sign in with a Google account, and click **"Get API key"**. |
| **OpenAI** (`gpt-4o`, `gpt-4o-mini`) | High-accuracy general OCR & document reasoning | Go to [OpenAI Platform](https://platform.openai.com/api-keys), sign up, and click **"Create new secret key"**. |
| **Anthropic Claude** (`claude-3-5-sonnet`) | Nuanced transcription & multi-column comprehension | Go to [Anthropic Console](https://console.anthropic.com/), sign up, and create an API key in your account settings. |
| **MinerU API** (`vlm`) | Complex book/document layout parsing & formula/table extraction | Go to [MinerU Web](https://mineru.net/), register a free account, and copy your API key from the user center. |
| **PaddleOCR** (`PaddleOCR-VL-1.6`) | Highly optimized Chinese, Japanese, and multilingual OCR | Go to [Baidu AI Studio / PaddleOCR](https://paddleocr.aistudio-app.com/) or [AI Studio](https://aistudio.baidu.com/), sign up, and generate an access token. |

### Setting Up Your `.env` File

1. In the project root folder, locate `.env.example` and create a copy named `.env`:
   - **Windows**: Copy `.env.example` and rename it to `.env` (or run `copy .env.example .env` in your terminal).
   - **macOS / Linux**: Run `cp .env.example .env` in your terminal.
2. Open `.env` in any text editor (Notepad, TextEdit, VS Code) and paste in the API keys for any services you wish to use:
   ```ini
   # Cloud Vision Models
   GEMINI_API_KEY=your_gemini_key_here
   OPENAI_API_KEY=your_openai_key_here
   ANTHROPIC_API_KEY=your_anthropic_key_here

   # Mineru API
   MINERU_API_KEY=your_mineru_key_here

   # PaddleOCR API (Baidu AI Studio)
   PADDLEOCR_API_KEY=your_paddleocr_token_here
   ```
3. Save the file and restart the application. Any configured engines will automatically appear in the **OCR Engine** dropdown in the Reading Desk!

---

## 💬 Ongoing Project, Feedback & Getting Help

This workbench is an **active, ongoing open-source project**. Archival materials, vertical Japanese typography, varying scan resolutions, and different operating systems can sometimes encounter edge cases or bugs.

**If something doesn't work, crashes, or if you have a feature idea, please let us know so we can address it!**

### How to Open an Issue (Beginner Friendly)

1. **Sign up for GitHub**: If you don't already have an account, create a free account at [github.com/signup](https://github.com/signup).
2. **Go to the Issues tab**: Visit the [**Issues Page for this repository**](https://github.com/azurebamboo/koshu-reading-workbench/issues).
3. **Click "New Issue"**: Click the green **New Issue** button near the top right.
4. **Describe the issue**:
   - What operating system you are using (Windows 10/11, macOS, Linux).
   - What document type you were processing (PDF, JPG, PNG, etc.).
   - What happened or what error message appeared (screenshots or error text are very helpful!).
5. **Submit**: Click **Submit new issue**. The creator will review your report and work to resolve the issue!

---

## 🛠️ Developer Mode

If you are developing or modifying the React frontend with hot-module reloading (HMR):

```bash
python scripts/skill_launcher.py start --dev
```

This boots the FastAPI backend on port `8000` and the Vite development server on port `5173`.

---

## 🙏 Special Thanks & Acknowledgements

This application relies on and extends the remarkable open-source work of:

- **[NDL-OCR / NDLOCR-Lite](https://github.com/ndl-lab/ndlocr-lite)**:
  Special thanks and deep gratitude to the **National Diet Library (NDL) Lab (国立国会図書館)** for developing and open-sourcing **NDL-OCR** and **NDLOCR-Lite**. Their specialized machine learning models for Japanese historical text, vertical typography, and archival documents power the core offline OCR capabilities of this workbench.
- **[Lucide Icons](https://lucide.dev/)**: For the clean UI icon library.
- **[FastAPI](https://fastapi.tiangolo.com/)** & **[Vite](https://vitejs.dev/)**: For the robust backend and modern frontend tooling.


