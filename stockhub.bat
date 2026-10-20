@echo off
rem StockHub: start/stop the local database (port 5433) and web app (http://localhost:3000).
rem Double-click to start (database + web, opens the browser), or: stockhub.bat start ^| stop ^| restart ^| status
rem The logic lives in scripts\stockhub.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stockhub.ps1" %*
