@echo off
rem ============================================
rem  Shelfmark - one-click launcher
rem  Starts the server silently (pythonw), waits
rem  until the port is ready, then opens the
rem  browser. Pure ASCII, no encoding issues.
rem  Double-click to run.
rem ============================================
setlocal
cd /d "%~dp0"

rem ---- locate pythonw (runs without a console window) ----
set "PYW=pythonw"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo [WARN] pythonw not found in PATH, falling back to python
  set "PYW=python"
)

start "" "%PYW%" app.py

rem Wait up to 15s for the server, then open browser
powershell -NoProfile -Command "try { $ok=$false; for($i=0;$i -lt 30;$i++){ try { $r=[System.Net.HttpWebRequest]::Create('http://127.0.0.1:5000/').GetResponse(); $r.Close(); $ok=$true; break } catch { Start-Sleep -Milliseconds 500 } }; if($ok){ Start-Process 'http://127.0.0.1:5000'; exit 0 } else { exit 1 } } catch { exit 1 }"

if errorlevel 1 (
  echo Server did not start within 15s.
  echo Check: port 5000 is free, python / pythonw available, then see data\app.log
  pause
)
