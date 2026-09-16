@echo off
REM ---------------------------------------------------------------------------
REM New-stack (06 push) launcher for the Windows production host.
REM
REM Why this exists: the new stack reads plain os.environ -- it has no .env
REM loader of its own, and it writes nothing to a log file (all output is
REM print()). Both are deployment-layer concerns, so this wrapper does them:
REM   1) load <root>\.deepseek_keys.env into this process's environment
REM   2) set PYTHONIOENCODING=utf-8 and append stdout+stderr to a log file
REM      (the Windows console is GBK and the card text carries emoji)
REM   3) run  python -m push swing   (board is pinned here; never short)
REM
REM Extra arguments are forwarded, so a manual check on the host is:
REM   deploy\run_push.bat --dry-run
REM
REM Keep this file ASCII-only + CRLF. See deploy\DEPLOY.md.
REM ---------------------------------------------------------------------------
setlocal
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
set "PY=C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe"
set "LOGDIR=%ROOT%\deploy\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM KEY=value lines, '#' starts a comment, no quoting in the file.
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\.deepseek_keys.env") do set "%%a=%%b"

set "PYTHONIOENCODING=utf-8"
cd /d "%ROOT%"
echo. >> "%LOGDIR%\push_swing.log"
echo ===== %DATE% %TIME% ===== >> "%LOGDIR%\push_swing.log"
"%PY%" -m push swing %* >> "%LOGDIR%\push_swing.log" 2>&1
exit /b %ERRORLEVEL%
