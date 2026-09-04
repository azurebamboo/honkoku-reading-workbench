#!/usr/bin/env python3
"""
1-Click Skill Installer for Standalone OCR & Reading Desk.
Runs the skill launcher bootstrapper to set up virtual environment, dependencies, and build the web interface.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
LAUNCHER_PATH = ROOT_DIR / "scripts" / "skill_launcher.py"

def main() -> None:
    print("Initializing Standalone OCR & Reading Desk Skill...")
    try:
        res = subprocess.run([sys.executable, str(LAUNCHER_PATH), "bootstrap"], check=True)
        if res.returncode == 0:
            print("\n[✓] Skill setup complete! You can now start the app anytime using:")
            print("    python scripts/skill_launcher.py start")
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Skill setup failed with exit code {e.returncode}.")
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
