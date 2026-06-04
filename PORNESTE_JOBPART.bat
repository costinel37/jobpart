@echo off
title JobPart Server - Port 8080
echo ============================================
echo   JobPart porneste pe http://localhost:8080
echo   Acces dashboard: http://localhost:8080/static/dashboard-angajator.html
echo   Nu inchide aceasta fereastra!
echo ============================================
cd /d "%~dp0backend"
python -m uvicorn main:app --port 8080 --reload
pause
