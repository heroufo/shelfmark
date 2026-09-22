@echo off
setlocal
cd /d "%~dp0"

set REPO=https://github.com/heroufo/shelfmark.git
set TAG=v1.1.0

echo ============================================================
echo   Shelfmark  -  publish to GitHub
echo ============================================================
echo.
echo  STEP 1  Do this in your browser FIRST
echo.
echo          https://github.com/new
echo            Owner        : heroufo
echo            Name         : shelfmark
echo            Visibility   : Public
echo            README / .gitignore / License  ->  check NONE of them
echo.
echo          (if you check any of them the push below will be rejected)
echo.
pause
echo.

where git >nul 2>nul
if errorlevel 1 (
  set GIT="C:\Program Files\Git\cmd\git.exe"
) else (
  set GIT=git
)

%GIT% rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo [ERROR] this folder is not a git repository
  echo         run this script from the project root folder
  pause
  exit /b 1
)

echo STEP 2  connect the remote
echo.
%GIT% remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo   adding origin  ->  %REPO%
  %GIT% remote add origin %REPO%
) else (
  echo   origin already exists, updating URL
  %GIT% remote set-url origin %REPO%
)
%GIT% remote -v
echo.

echo STEP 3  push branch main
echo   a browser window may pop up for GitHub login - that is normal
echo.
%GIT% push -u origin main
if errorlevel 1 (
  echo.
  echo [FAILED] push was rejected.
  echo   If the remote already has commits, run:
  echo       git pull --rebase origin main
  echo   then run this script again.
  echo.
  pause
  exit /b 1
)

echo.
set PUSHTAG=N
set /p PUSHTAG=Also push tag %TAG% ? [y/N] 
if /i "%PUSHTAG%"=="y" (
  echo.
  echo pushing tag %TAG% ...
  %GIT% push origin %TAG%
)

echo.
echo ============================================================
echo   Done.  Your repository:
echo     https://github.com/heroufo/shelfmark
echo   CI (Actions) starts automatically on the first push.
echo ============================================================
echo.
echo   Next, optional:
echo     - Releases page  ->  draft a release from tag %TAG%
echo       attach  dist_exe\Shelfmark.exe   (the exe alone is safe;
echo       never upload data\ or covers\ - that is your private library)
echo.
pause
endlocal
