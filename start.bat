@echo off
setlocal

cd /d "%~dp0"

echo Iniciando Lads Beer...
docker compose up -d

echo.
echo Lads Beer iniciado!
echo Acesse: http://localhost:8000
pause
