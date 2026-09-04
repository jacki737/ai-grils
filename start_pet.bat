@echo off
title AI Girlfriend
cd /d "%~dp0"

echo [1/2] starting backend...
start "AI-backend" /min "D:\py13\python.exe" run_server.py

echo [2/2] waiting for server...
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:9000/api/personas' -UseBasicParsing -TimeoutSec 2;if($r.StatusCode -eq 200){break}}catch{Start-Sleep -Milliseconds 500}}"

set EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
start "" "%EDGE%" --app=http://127.0.0.1:9000/static/jarvis.html --window-size=1280,800

echo Started!
timeout /t 3 >nul
