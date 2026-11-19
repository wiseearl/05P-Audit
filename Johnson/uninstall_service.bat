@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ======================================================
echo   MCP Server - Windows NSSM 服務一鍵卸載程式 (V2 企業版)
echo ======================================================
echo.

:: 1. 檢查是否具備系統管理員身分
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [錯誤] 權限不足！請在此批次檔點擊右鍵，選擇「以系統管理員身分執行」。
    echo.
    pause
    exit /b 1
)

:: 2. 定義目錄與 NSSM
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "NSSM_EXE="
if exist "%APP_DIR%\nssm\nssm.exe" set "NSSM_EXE=%APP_DIR%\nssm\nssm.exe"
if not defined NSSM_EXE if exist "%APP_DIR%\nssm.exe" set "NSSM_EXE=%APP_DIR%\nssm.exe"
if not defined NSSM_EXE (
    for /f "tokens=*" %%i in ('where nssm 2^>nul') do (
        if not defined NSSM_EXE set "NSSM_EXE=%%i"
    )
)

:: 3. 雙向清理服務 (同時檢查 MCP_Server_Johnson 與 MCP_Johnson_Server)
for %%s in (MCP_Server_Johnson MCP_Johnson_Server) do (
    sc query %%s >nul 2>&1
    if !errorlevel! equ 0 (
        echo [資訊] 偵測到服務 %%s，正在停止並移除...
        if defined NSSM_EXE (
            "!NSSM_EXE!" stop %%s >nul 2>&1
            "!NSSM_EXE!" remove %%s confirm >nul 2>&1
        )
        sc stop %%s >nul 2>&1
        sc delete %%s >nul 2>&1
        echo [資訊] 服務 %%s 已完成清除。
    )
)

timeout /t 2 /nobreak >nul
echo.
echo ======================================================
echo   卸載結果確認：
echo ======================================================
sc query MCP_Server_Johnson >nul 2>&1
if %errorlevel% neq 0 (
    echo [成功] 服務已徹底自 Windows 系統卸載與清除！
) else (
    echo [提示] 服務可能仍在釋放資源中，可重開工作管理員確認。
)
echo.
pause
