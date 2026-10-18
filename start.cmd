@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "FABRIX_EXIT=%ERRORLEVEL%"
if not "%FABRIX_EXIT%"=="0" (
  echo.
  echo Fabrix startup failed. Review the error above and try again.
  pause
)
exit /b %FABRIX_EXIT%
