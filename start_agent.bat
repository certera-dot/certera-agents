@echo off
title Trading Agent — Modo Simulacion
color 0A
echo.
echo  =========================================
echo   TRADING AGENT - Iniciando...
echo   Modo: MANUAL  ^|  Simulacion: TRUE
echo  =========================================
echo.

cd /d "%~dp0"

:: Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ y reintenta.
    pause
    exit /b 1
)

:: Instalar dependencias si no están
echo Verificando dependencias...
pip install -r requirements.txt -q --break-system-packages 2>nul
pip install socksio -q --break-system-packages 2>nul

echo.
echo Iniciando agente...
echo.
python main.py

echo.
echo [El agente se detuvo]
pause
