@echo off
rem ============================================================
rem  Rename this project folder to "shelfmark" and leave a
rem  directory junction with the old name, so existing desktop
rem  shortcuts and the Startup auto-run keep working.
rem
rem  IMPORTANT: close WorkBuddy / editors / file explorer windows /
rem  sync clients first.  While the project folder is held open,
rem  Windows refuses the rename and the script will tell you so.
rem
rem  Extra options are passed straight through, e.g.
rem      rename-folder.cmd --dry-run
rem      rename-folder.cmd --no-junction
rem      rename-folder.cmd --to my-library
rem ============================================================
setlocal
title Rename project folder

rem Move this shell out of the project folder first: a shell whose
rem current directory is the project would block the rename.
cd /d C:\

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] "python" was not found in PATH.
  echo Install Python 3.9+ or run the helper directly, e.g.
  echo     "C:\path\to\python.exe" tools\rename_project_folder.py
  echo.
  pause
  exit /b 1
)

python "%~dp0tools\rename_project_folder.py" %*
echo.
pause
exit /b %errorlevel%
