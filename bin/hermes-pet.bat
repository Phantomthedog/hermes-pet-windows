@echo off
REM Hermes Pet — Windows batch launcher
REM Derives project root from script location.
REM Usage:
REM   hermes-pet status          Show overlay + bridge status
REM   hermes-pet start-all       Start overlay + bridge
REM   hermes-pet stop-all        Stop overlay + bridge
REM   hermes-pet restart-all     Restart everything
REM   hermes-pet test-event <s>  Send a fake state to overlay
REM   hermes-pet doctor          Run diagnostics
REM   hermes-pet logs bridge     View bridge logs

setlocal enabledelayedexpansion

set COMMAND=%1
if "%COMMAND%"=="" set COMMAND=status
set ARG=%2

REM Derive project root from this script's location (%~dp0 = bin/)
set PROJECT_DIR=%~dp0
REM Remove trailing backslash and /bin suffix to get project root
if "%PROJECT_DIR:~-1%"=="\" set PROJECT_DIR=%PROJECT_DIR:~0,-1%
for %%I in ("%PROJECT_DIR%") do set PROJECT_DIR=%%~dpI
if "%PROJECT_DIR:~-1%"=="\" set PROJECT_DIR=%PROJECT_DIR:~0,-1%

REM Convert to WSL path: C:\foo\bar → /mnt/c/foo/bar
set WSL_PROJECT_DIR=%PROJECT_DIR:\=/%
set WSL_DRIVE=%WSL_PROJECT_DIR:~0,1%
set WSL_PROJECT_DIR=/mnt/%WSL_DRIVE%%WSL_PROJECT_DIR:~2%

set WSL_SCRIPT=%WSL_PROJECT_DIR%/bin/hermes-pet

if not "%ARG%"=="" (
    wsl bash -c "cd %WSL_PROJECT_DIR% && bash %WSL_SCRIPT% %COMMAND% %ARG%"
) else (
    wsl bash -c "cd %WSL_PROJECT_DIR% && bash %WSL_SCRIPT% %COMMAND%"
)
