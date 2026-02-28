@echo off
title AI Cowork
echo ============================================
echo  AI Cowork — Screen Reader + Chat Assistant
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: Check Tesseract
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo [WARN] Tesseract OCR not found at default path.
    echo        Install from: https://github.com/UB-Mannheim/tesseract/wiki
    echo        Or set TESSERACT_PATH in .env
    echo.
)

:: Install Python deps
echo Installing Python dependencies...
pip install -r requirements.txt -q

:: Start Ollama in Docker
echo Starting Ollama (Docker)...
docker compose up -d ollama model-loader

:: Wait for Ollama
echo Waiting for Ollama to be ready...
:wait_ollama
timeout /t 3 /nobreak >nul
docker exec cowork-ollama ollama list >nul 2>&1
if %errorlevel% neq 0 goto wait_ollama
echo Ollama is ready!
echo.

:: Start the app
echo Starting AI Cowork...
echo Dashboard: http://localhost:8080
echo.
python app.py
