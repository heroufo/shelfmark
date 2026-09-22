@echo off
rem ============================================================
rem  One-click repack: rebuild the single-file exe
rem  Steps:
rem    1) generate logo + exe icon (tools\make_logo.py, make_icon.py)
rem    2) run PyInstaller onefile (shelfmark.spec)
rem    3) sync latest library.json + covers into dist_exe\
rem  Output: dist_exe\  (portable folder, copy to any PC)
rem  Prereq: pip install -r requirements-dev.txt
rem ============================================================
setlocal
cd /d "%~dp0"

rem ---- python: interpreter used to build (needs pyinstaller) ----
set "PY=python"
where %PY% >nul 2>nul
if errorlevel 1 (
  echo [ERROR] "python" not found in PATH.
  echo Install Python 3.9+ and make sure it is on PATH, then rerun.
  pause
  exit /b 1
)

echo [1/3] generate logo + exe icon ...
"%PY%" tools\make_logo.py
if errorlevel 1 goto :fail
"%PY%" make_icon.py
if errorlevel 1 goto :fail

echo [2/3] PyInstaller packaging (about 1 min) ...
"%PY%" -m PyInstaller --noconfirm --clean --distpath dist_exe shelfmark.spec
if errorlevel 1 goto :fail

echo [3/3] sync latest library.json + covers into dist_exe ...
copy /Y "data\library.json" "dist_exe\data\library.json" >nul
if not exist "dist_exe\covers" mkdir "dist_exe\covers"
xcopy "static\covers\*.jpg"  "dist_exe\covers\" /Y /Q >nul
xcopy "static\covers\*.png"  "dist_exe\covers\" /Y /Q >nul
xcopy "static\covers\*.svg"  "dist_exe\covers\" /Y /Q >nul
xcopy "static\covers\*.webp" "dist_exe\covers\" /Y /Q >nul

echo.
echo Done. Rebuilt exe with the latest library is in:
echo   dist_exe\  (copy this whole folder to use elsewhere)
pause
exit /b 0

:fail
echo [ERROR] step failed, see messages above.
pause
exit /b 1
