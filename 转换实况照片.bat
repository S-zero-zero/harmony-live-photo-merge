@echo off
rem ============================================================
rem  Entry point: double-click to build the HarmonyOS Live Photo.
rem  No argument  -> batch mode: convert EVERY same-name JPG+MP4
rem                  pair found in input\ into out\, printing all
rem                  verification items for each pair.
rem  With args    -> single pair: %1 %2 %3  (image, video, output)
rem
rem  This is a thin wrapper around main.py, which is the real
rem  command-line entry point.
rem
rem  NOTE: keep this file ASCII-only. cmd parses .bat with the
rem  OEM code page before "chcp" takes effect, so non-ASCII text
rem  here would be mangled. All Chinese messages are printed by
rem  the Python script instead.
rem ============================================================
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3 and add it to PATH, then retry.
    echo.
    pause
    exit /b 1
)

python "main.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [DONE] All output is ready in the out\ folder.
    echo        Keep the .jpg extension when transferring.
    echo        Do NOT use channels that re-encode the image
    echo        ^(e.g. WeChat/QQ "send original", photo editors^).
) else if "%RC%"=="2" (
    echo [ABORTED] Bad input, nothing was written.
    echo           Check the message above.
) else (
    echo [FAILED] Some pairs failed verification, exit code %RC%.
    echo          Do NOT use the ones marked FAIL.
)
echo.
pause
exit /b %RC%
