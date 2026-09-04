@echo off
echo Starting Koshu Standalone OCR ^& Reading Desk...
echo.

if exist "%~dp0koshu-ocr-backend.exe" (
    echo Starting compiled binary server...
    start "" "%~dp0koshu-ocr-backend.exe"
    timeout /t 3 /nobreak >nul
    start http://localhost:8000/
    echo Server is running on http://localhost:8000/
    echo Press any key in this window to stop the server...
    pause >nul
    taskkill /f /im koshu-ocr-backend.exe >nul 2>&1
) else if exist "%~dp0dist\koshu-ocr-backend\koshu-ocr-backend.exe" (
    echo Starting compiled binary server...
    start "" "%~dp0dist\koshu-ocr-backend\koshu-ocr-backend.exe"
    timeout /t 3 /nobreak >nul
    start http://localhost:8000/
    echo Server is running on http://localhost:8000/
    echo Press any key in this window to stop the server...
    pause >nul
    taskkill /f /im koshu-ocr-backend.exe >nul 2>&1
) else (
    echo Compiled binary release not found. Launching via Python launcher...
    if "%~1"=="" (
        python "%~dp0scripts\skill_launcher.py" start
    ) else (
        python "%~dp0scripts\skill_launcher.py" %*
    )
)
