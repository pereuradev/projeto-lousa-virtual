@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo A instalacao falhou. Leia a mensagem acima e o LEIA-ME.md.
    pause
    exit /b 1
)
echo.
echo Tudo pronto. Abra "Iniciar Lousa.cmd".
pause
