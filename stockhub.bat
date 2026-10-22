@echo off
rem StockHub: start/stop the local database (port 5433) and web app (http://127.0.0.1:3000).
rem Double-click to start (database + web, opens the browser); stockhub-stop.bat stops both.
rem Or: stockhub.bat start ^| stop ^| restart ^| status ^| dev
rem The logic lives in scripts\stockhub.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stockhub.ps1" %*
