@echo off
echo Starting Koshu Standalone OCR & Reading Desk...
echo This command prompt window will stay open to run the local OCR server.
echo Closing this window will stop the server.
echo.

:: Start the backend server
start "" "%~dp0dist\koshu-ocr-backend\koshu-ocr-backend.exe"

:: Wait 3 seconds for the server to initialize
timeout /t 3 /nobreak >nul

:: Open default web browser to the local server
start http://localhost:8000/

echo Server is running on http://localhost:8000/
echo Press any key in this window to stop the server...
pause >nul

:: Kill the backend server on exit
taskkill /f /im koshu-ocr-backend.exe >nul 2>&1
