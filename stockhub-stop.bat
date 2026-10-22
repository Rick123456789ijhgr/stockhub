@echo off
rem StockHub: double-click to stop the web app and the local database (same as stockhub.bat stop).
rem Scheduled tasks still start the database when they run.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stockhub.ps1" stop
