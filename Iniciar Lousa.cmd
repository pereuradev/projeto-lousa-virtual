@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo O ambiente da lousa ainda nao esta pronto.
    echo Execute "Instalar ou reparar.cmd" nesta pasta.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py" %*
