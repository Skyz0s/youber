@echo off
setlocal EnableExtensions
REM ============================================================
REM  Demo de BARF / youber - version Windows
REM  Uso: examples\demo.bat [URL]
REM    (URL por defecto: https://example.com)
REM  Pausas entre pasos; desactivalas con:  set DEMO_FAST=1
REM ============================================================

set "URL=%~1"
if "%URL%"=="" set "URL=https://example.com"
set "ROOT=%~dp0.."

REM Localizar el entorno: venv del proyecto o instalacion global
if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
  set "AUDIT=%ROOT%\.venv\Scripts\youber-audit.exe"
  set "SANDBOX=%ROOT%\.venv\Scripts\youber-sandbox.exe"
) else (
  set "PY=python"
  set "AUDIT=youber-audit"
  set "SANDBOX=youber-sandbox"
)

call :banner

echo.
echo [1/3] Auditoria de accesibilidad (axe-core + WCAG 2.1/2.2)
echo ------------------------------------------------------------
call "%AUDIT%" "%URL%"
call :pause

echo.
echo [2/3] Sandbox: region JP + iPhone + red 3g
echo ------------------------------------------------------------
call "%SANDBOX%" --url "%URL%" --region JP --device iPhone --speed 3g
call :pause

echo.
echo [3/3] Cliente MCP end-to-end (servidor real por stdio)
echo ------------------------------------------------------------
call "%PY%" "%ROOT%\examples\demo_mcp.py" "%URL%"
call :pause

echo.
echo ============================================================
echo   Demo completada.
echo   - Reporte Markdown en: %ROOT%\reports\
echo   - Proyecto: https://github.com/Skyz0s/youber
echo   - PyPI:     pip install youber
echo ============================================================
exit /b 0

:pause
if "%DEMO_FAST%"=="1" exit /b 0
echo.
pause > nul
exit /b 0

:banner
echo ============================================================
echo   BARF / youber - Browser Automation Research Framework
echo ============================================================
echo   URL de la demo: %URL%
echo.
exit /b 0
