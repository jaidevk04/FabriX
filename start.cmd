@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "AVENOR_EXIT=%ERRORLEVEL%"
if not "%AVENOR_EXIT%"=="0" (
  echo.
  echo Avenor startup failed. Review the error above and try again.
  pause
)
exit /b %AVENOR_EXIT%
