@echo off
chcp 65001 > nul
cd /d "%~dp0\.."
"C:\Users\이홍원\Desktop\code_training\chzzk_downloader\.venv\Scripts\python.exe" "tools\preview_ui_feedbacks.py"
if %errorlevel% neq 0 (
    echo.
    echo 실행 중 오류가 발생했습니다.
    pause
)
