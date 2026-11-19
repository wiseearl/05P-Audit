@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ======================================================
echo   MCP Server - Windows NSSM 服務一鍵安裝程式 (V2 企業版)
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

:: 2. 定義服務名稱與目錄
set "SERVICE_NAME=MCP_Server_Johnson"
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
set "SUPERVISOR_PY=%APP_DIR%\supervisor.py"

:: 3. 確保專案自包含 nssm.exe (優先本地 -> 系統 PATH -> 官方網站自動下載)
set "NSSM_EXE="
if exist "%APP_DIR%\nssm\nssm.exe" set "NSSM_EXE=%APP_DIR%\nssm\nssm.exe"
if not defined NSSM_EXE if exist "%APP_DIR%\nssm.exe" set "NSSM_EXE=%APP_DIR%\nssm.exe"
if not defined NSSM_EXE (
    for /f "tokens=*" %%i in ('where nssm 2^>nul') do (
        if not defined NSSM_EXE (
            echo [資訊] 偵測到系統 PATH 中的 NSSM，正在複製至專案專屬 nssm 目錄...
            mkdir "%APP_DIR%\nssm" 2>nul
            copy /y "%%i" "%APP_DIR%\nssm\nssm.exe" >nul 2>&1
            if exist "%APP_DIR%\nssm\nssm.exe" (
                set "NSSM_EXE=%APP_DIR%\nssm\nssm.exe"
            ) else (
                set "NSSM_EXE=%%i"
            )
        )
    )
)

if not defined NSSM_EXE (
    echo [資訊] 本機未偵測到 nssm.exe，正在從 NSSM 官方網站自動下載（約需 10~30 秒）...
    call :download_nssm
    if exist "%APP_DIR%\nssm\nssm.exe" (
        echo [成功] 已從官方網站下載並完成 SHA-256 校驗: "%APP_DIR%\nssm\nssm.exe"
        set "NSSM_EXE=%APP_DIR%\nssm\nssm.exe"
    )
)

if not defined NSSM_EXE (
    echo [錯誤] 找不到 nssm.exe 且自動下載失敗！（可能無外網連線或遭防火牆阻擋）
    echo [離線指引] 請至 https://nssm.cc/download 下載 nssm-2.24.zip，
    echo            取出 win64\nssm.exe 放置於以下路徑後重新執行：
    echo            "%APP_DIR%\nssm\nssm.exe"
    echo.
    pause
    exit /b 1
)

:: 4. 動態鎖定當前環境之 Python 解譯器實體絕對路徑 (解決 SYSTEM 帳號 PATH 缺失)
set "PYTHON_EXE="
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    set "PYTHON_EXE=%%i"
)
if not defined PYTHON_EXE (
    for /f "tokens=*" %%i in ('where python 2^>nul') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
    )
)

if not defined PYTHON_EXE (
    echo [錯誤] 找不到可用的 Python 解譯器！請確認 Python 已安裝並已加入 PATH。
    echo.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [錯誤] 解析到的 Python 執行檔路徑不存在: "%PYTHON_EXE%"
    echo.
    pause
    exit /b 1
)

echo [資訊] 專案 NSSM : "!NSSM_EXE!"
echo [資訊] Python 實體: "!PYTHON_EXE!"
echo [資訊] 服務名稱  : %SERVICE_NAME%
echo [資訊] 專案目錄  : %APP_DIR%
echo [資訊] 守護腳本  : %SUPERVISOR_PY%
echo.

:: 5. 雙向清理歷史殘留服務 (相容清理 MCP_Server_Johnson 與 MCP_Johnson_Server)
for %%s in (MCP_Server_Johnson MCP_Johnson_Server) do (
    sc query %%s >nul 2>&1
    if !errorlevel! equ 0 (
        echo [提示] 偵測到既有服務 %%s，正在停止並清除...
        "!NSSM_EXE!" stop %%s >nul 2>&1
        "!NSSM_EXE!" remove %%s confirm >nul 2>&1
        sc stop %%s >nul 2>&1
        sc delete %%s >nul 2>&1
        timeout /t 2 /nobreak >nul
    )
)

:: 6. 註冊 NSSM 服務 (直接綁定 Python 解譯器，繞過批次檔)
echo [1/4] 正在註冊 NSSM 服務...
"!NSSM_EXE!" install %SERVICE_NAME% "!PYTHON_EXE!"
if %errorlevel% neq 0 (
    echo [錯誤] 服務安裝失敗！
    pause
    exit /b 1
)

echo [2/4] 正在配置參數、工作目錄與 UTF-8 環境...
"!NSSM_EXE!" set %SERVICE_NAME% AppParameters "%SUPERVISOR_PY%"
"!NSSM_EXE!" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"!NSSM_EXE!" set %SERVICE_NAME% DisplayName "MCP Internal FAQ & Audit Service (Johnson)"
"!NSSM_EXE!" set %SERVICE_NAME% Description "Streamable HTTP MCP Server with unified gateway and self-update."
"!NSSM_EXE!" set %SERVICE_NAME% Start SERVICE_AUTO_START
"!NSSM_EXE!" set %SERVICE_NAME% AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "PYTHONUTF8=1"

echo [3/4] 正在配置重啟延遲與輸出日誌導流...
"!NSSM_EXE!" set %SERVICE_NAME% AppRestartDelay 3000
mkdir "%APP_DIR%\logs" 2>nul
"!NSSM_EXE!" set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\nssm_stdout.log"
"!NSSM_EXE!" set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\nssm_stderr.log"

echo [4/4] 正在啟動服務...
"!NSSM_EXE!" start %SERVICE_NAME%

timeout /t 3 /nobreak >nul
echo.
echo ======================================================
echo   安裝完成！服務狀態：
echo ======================================================
sc query %SERVICE_NAME% | findstr /i "STATE"
echo.
echo [提示] 可至 logs\nssm_stdout.log 與 logs\nssm_stderr.log 檢視服務即時輸出。
echo.
pause
exit /b 0

:download_nssm
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"
set "NSSM_SHA256=727D1E42275C605E0F04ABA98095C38A8E1E46DEF453CDFFCE42869428AA6743"
set "NSSM_ARCH=win64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "NSSM_ARCH=win32"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$ProgressPreference='SilentlyContinue';" ^
    "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
    "$tmpDir=Join-Path $env:TEMP ('nssm_dl_' + [guid]::NewGuid().ToString('N'));" ^
    "$zipPath=Join-Path $tmpDir 'nssm.zip';" ^
    "$targetDir=Join-Path $env:APP_DIR 'nssm';" ^
    "$targetExe=Join-Path $targetDir 'nssm.exe';" ^
    "try {" ^
    "  New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null;" ^
    "  Invoke-WebRequest -Uri $env:NSSM_URL -OutFile $zipPath -UseBasicParsing -TimeoutSec 60;" ^
    "  $actual=(Get-FileHash -Path $zipPath -Algorithm SHA256).Hash;" ^
    "  if ($actual -ne $env:NSSM_SHA256) { throw ('SHA256 mismatch: ' + $actual) };" ^
    "  Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force;" ^
    "  $src=Join-Path $tmpDir ('nssm-2.24\' + $env:NSSM_ARCH + '\nssm.exe');" ^
    "  if (-not (Test-Path $src)) { throw ('Missing ' + $src) };" ^
    "  New-Item -ItemType Directory -Force -Path $targetDir | Out-Null;" ^
    "  Copy-Item -Path $src -Destination $targetExe -Force;" ^
    "} catch {" ^
    "  Write-Host ('[ERROR_SUMMARY] ' + $_.Exception.GetType().Name + ': ' + $_.Exception.Message);" ^
    "  exit 1;" ^
    "} finally {" ^
    "  if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue };" ^
    "}"
exit /b %errorlevel%
