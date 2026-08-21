@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "MONITOR_URL=http://127.0.0.1:8765"

start "PSQZA Formal Monitor" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\run_formal_monitor.ps1"
if errorlevel 1 goto :startup_error

for /L %%I in (1,1,60) do (
  powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%MONITOR_URL%/api/state' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 goto :ready
  timeout /t 1 /nobreak >nul
)

:startup_error
echo ERROR: O monitor PSQZA nao respondeu em %MONITOR_URL%.
echo Consulte a janela PowerShell do monitor para o diagnostico.
pause
exit /b 1

:ready
start "" "%MONITOR_URL%"
exit /b 0
