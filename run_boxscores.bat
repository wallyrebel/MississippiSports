@echo off
REM ============================================================
REM NEMCC Box Score Automation
REM Runs daily via Windows Task Scheduler
REM Discovers, scrapes, rewrites, and publishes box score articles
REM ============================================================

echo [%date% %time%] Starting NEMCC Box Score processing...

REM Navigate to the project directory
cd /d "C:\Users\myers\OneDrive\Desktop\MississippiSports"

REM Load environment variables from .env file
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "%%a=%%b"
)

REM Run the box score pipeline (last 48 hours only)
python -m rss_to_wp boxscores

echo [%date% %time%] NEMCC Box Score processing complete.
