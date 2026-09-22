@echo off
setlocal
cd /d "%~dp0"

set REPO=https://github.com/heroufo/shelfmark.git
set TAG=v1.1.0
set PROXY_PORT=7890
set PROXY=
set TMPF=%TEMP%\shelfmark_ls.txt

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
echo            README / .gitignore / License  -^>  check NONE of them
echo.
echo          Click the green "Create repository" button, then come
echo          back here and press a key.
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
if errorlevel 1 goto :not_a_repo

netstat -an | findstr /C:"127.0.0.1:%PROXY_PORT%" >nul 2>nul
if errorlevel 1 goto :no_proxy
set PROXY=-c http.proxy=http://127.0.0.1:%PROXY_PORT% -c https.proxy=http://127.0.0.1:%PROXY_PORT%
echo  using local proxy 127.0.0.1:%PROXY_PORT%
goto :probe

:no_proxy
echo  no proxy on 127.0.0.1:%PROXY_PORT% - will try a direct connection

:probe
echo.
echo  STEP 2  check the repository and the network
echo.
%GIT% %PROXY% ls-remote --heads "%REPO%" > "%TMPF%" 2>&1
if errorlevel 1 goto :probe_failed
echo    OK - repository found and reachable
goto :remote

:probe_failed
findstr /I /C:"not found" /C:"404" "%TMPF%" >nul 2>nul
if not errorlevel 1 goto :repo_missing
goto :net_fail

:remote
echo.
echo  STEP 3  connect the remote
echo.
%GIT% remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo    adding origin
  %GIT% remote add origin %REPO%
) else (
  echo    origin already exists - updating its URL
  %GIT% remote set-url origin %REPO%
)
%GIT% remote -v
echo.

echo  STEP 4  push branch main
echo     a browser window may pop up for GitHub login - that is normal
echo.
%GIT% %PROXY% push -u origin main
if errorlevel 1 goto :push_failed

echo.
set PUSHTAG=N
set /p PUSHTAG=Also push tag %TAG% ? [y/N] 
if /i "%PUSHTAG%"=="y" (
  echo.
  echo  pushing tag %TAG% ...
  %GIT% %PROXY% push origin %TAG%
)

echo.
echo ============================================================
echo   Done.  Your repository:
echo     https://github.com/heroufo/shelfmark
echo   CI / Actions starts automatically on the first push.
echo ============================================================
echo.
echo   Next, optional:
echo     - Releases page  -^>  draft a release from tag %TAG%
echo       attach the single file  dist_exe\Shelfmark.exe
echo       never upload the folders data\ or covers\  -  that is your private library
echo.
pause
exit /b 0

:not_a_repo
echo.
echo [ERROR] this folder is not a git repository.
echo         Put this script in the project root and run it from there.
echo.
pause
exit /b 1

:repo_missing
echo.
echo [ERROR] GitHub says that repository does not exist yet.
echo         Create it first - it takes 30 seconds:
echo.
echo           https://github.com/new
echo             Owner       : heroufo
echo             Name        : shelfmark
echo             Visibility  : Public
echo             README / .gitignore / License  -^>  check NONE of them
echo.
echo         Then run this script again.
echo.
pause
exit /b 1

:net_fail
echo.
echo [ERROR] cannot reach github.com.
echo         Raw message from git:
echo.
type "%TMPF%"
echo.
echo         GitHub over HTTPS is often blocked or throttled in mainland
echo         China - this is a network issue, not a problem with your repo.
echo.
echo         What to do:
echo           1. start your local proxy  -  Clash / v2ray / shadowsocks
echo           2. this script auto-detects a proxy on 127.0.0.1:%PROXY_PORT%
echo           3. if yours listens on a different port, change PROXY_PORT
echo              near the top of this script
echo           4. run this script again
echo.
pause
exit /b 1

:push_failed
echo.
echo [ERROR] the push did not go through - see the output above.
echo.
echo         Says "rejected" or "non-fast-forward" ?
echo           the remote already has commits, run:
echo               git pull --rebase origin main
echo           then run this script again.
echo.
echo         Says "unable to access" or "Connection was reset" ?
echo           it is a network problem - start your local proxy and
echo           run this script again.
echo.
pause
exit /b 1
