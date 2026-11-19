@echo off
chcp 65001 >nul
echo 正在啟動 Grace 稽核資料庫分析 MCP 伺服器...
python server.py
pause
