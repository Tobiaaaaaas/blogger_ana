@echo off
REM ---------------------------------------------------------------------------
REM New-stack (06 push) launcher for the Windows production host.
REM
REM Usage:  run_push.bat <short|swing> [--force] [--dry-run] [--init]
REM
REM Why this exists: the new stack reads plain os.environ -- it has no .env
REM loader of its own, and it writes nothing to a log file (all output is
REM print()). Both are deployment-layer concerns, so this wrapper does them:
REM   1) load <root>\.deepseek_keys.env into this process's environment
REM   2) set PYTHONIOENCODING=utf-8 and append stdout+stderr to a per-board log
REM      (the Windows console is GBK and the card text carries emoji)
REM   3) run  python -m push <board>
REM
REM The BOARD IS REQUIRED and is the first argument -- both boards run on this
REM host now (PushSwing*/PushShort* tasks in register_tasks.ps1), so there is no
REM safe default to guess. Everything after it is forwarded, so a manual check
REM on the host is:  deploy\run_push.bat swing --dry-run
REM
REM Keep this file ASCII-only + CRLF. See deploy\DEPLOY.md.
REM ---------------------------------------------------------------------------
setlocal
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
set "PY=C:\Users\24966\AppData\Local\Programs\Python\Python311\python.exe"
set "LOGDIR=%ROOT%\deploy\logs"

set "BOARD=%~1"
if "%BOARD%"=="" (
  echo usage: run_push.bat ^<short^|swing^> [--force] [--dry-run] [--init]
  exit /b 2
)
shift

REM cmd's %* is NOT updated by shift, so rebuild the tail explicitly.
set "TAIL="
:args
if "%~1"=="" goto :args_done
set "TAIL=%TAIL% %~1"
shift
goto :args
:args_done

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM KEY=value lines, '#' starts a comment, no quoting in the file.
REM findstr first, so that only ASSIGNMENT lines reach for /f. cmd reads this
REM file in the OEM codepage; a UTF-8 Chinese comment can swallow its own line
REM break, and the KEY=value line after it then merges into the comment and is
REM LOST. That is exactly how FEISHU_WEBHOOK_URL_SWING went missing on the
REM first real push (2026-09-16): the push ran to the end and the card was
REM never sent, leaving only one "not configured" line in the log. ASCII-only
REM lines cannot hit that. Do NOT go back to reading the file directly.
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /r /b "[A-Z_][A-Z0-9_]*=" "%ROOT%\.deepseek_keys.env"`) do set "%%a=%%b"

set "PYTHONIOENCODING=utf-8"
cd /d "%ROOT%"
echo. >> "%LOGDIR%\push_%BOARD%.log"
echo ===== %DATE% %TIME% ===== >> "%LOGDIR%\push_%BOARD%.log"
"%PY%" -m push %BOARD% %TAIL% >> "%LOGDIR%\push_%BOARD%.log" 2>&1
exit /b %ERRORLEVEL%
