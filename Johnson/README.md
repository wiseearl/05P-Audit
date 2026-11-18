# 區網遠端維運與內部知識庫 MCP Server (MCP v2)

本專案用於在區網另一台機器架設 **Streamable HTTP MCP Server**，供本地 Antigravity IDE Agent 跨機連線呼叫，具備**企業內部模擬知識庫查詢**、**IIS / NSSM / Windows 服務狀態與日誌探針**、**通用遠端檔案讀寫**，以及**安全自身熱更新（Self-Update）與災難還原**能力。

## 檔案說明

- `server.py`：以 MCP v2 `MCPServer` + `uvicorn` 實作的 Streamable HTTP MCP 主程式（預設監聽 `0.0.0.0:8000/mcp`，完整 11 個工具詳見第 4 節）。
- `supervisor.py`：Python 原生守護行程（Supervisor），負責支援完整 UTF-8 輸出、偵測 `Exit Code 0` 自動熱重啟，以及連續異常崩潰 3 次自動以 `server.py.bak` 還原。
- `run_server.bat`：Windows 一鍵啟動腳本（切換 UTF-8 `chcp 65001` 後啟動 `supervisor.py`）。
- `faq_data.json`：模擬企業內部知識庫資料（每次工具呼叫會即時讀取，修改後無須重啟 Server）。
- `requirements.txt`：Python 相依套件清單（`mcp>=2.0.0`）。
- `mcp_config.example.json`：本地 Antigravity IDE MCP 連線設定範本。
- `.gitignore`：專屬於 `Johnson/` 目錄的 Git 忽略規則（不影響其他專案資料夾）。

---

## 1. 遠端機台架設步驟（另一台區網電腦）

1. 安裝相依套件（確保安裝 MCP v2）：
   ```powershell
   pip install -r requirements.txt
   ```
2. 開放 Windows 防火牆 `8000` Port（以系統管理員身分執行 PowerShell）：
   ```powershell
   New-NetFirewallRule -DisplayName "MCP Server 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```
3. 啟動 MCP Server（**須透過 Supervisor 啟動才支援熱更新自動重啟**）：
   ```powershell
   .\run_server.bat
   # 或直接執行守護行程：
   python supervisor.py
   ```
   - 透過 `run_server.bat` / `supervisor.py` 啟動，才能支援 `apply_server_update`、`rollback_server` 的**自動重啟**與連續崩潰自動還原（`server.py.bak`）。
   - 若僅單獨執行 `python server.py`，觸發熱更新後程式會在 1.5 秒後直接結束而**不會**自動重啟。
   - 啟動後終端機將顯示端點位址，例如：`http://<遠端機台區網IP>:8000/mcp`（可透過環境變數 `MCP_HOST` 與 `MCP_PORT` 覆寫預設綁定位址與連接埠）。

---

## 2. 本地 Antigravity IDE 連線設定步驟

### 步驟 A：建立/修改 MCP 設定檔
1. 開啟檔案總管，進入使用者設定資料夾：
   `%USERPROFILE%\.gemini\config\`（即 `C:\Users\<你的使用者名稱>\.gemini\config\`）。
   *若無 `config` 資料夾請手動建立。*
2. 參考 `mcp_config.example.json` 建立或編輯 `mcp_config.json`，將 `<遠端機台區網IP>` 替換為步驟 1 取得的實際 IP（**務必保留 `http://` 前綴**）：
   ```json
   {
     "mcpServers": {
       "internal-faq-lan": {
         "url": "http://<遠端機台區網IP>:8000/mcp"
       }
     }
   }
   ```

### 步驟 B：在 IDE 介面確認狀態
1. 在 Antigravity IDE（各版本位置可能略有差異）對話窗口左上 Toggle Sidebar 中開啟 **Customizations > Installed**。
2. 找到 **MCP Servers**。
3. 確認列表中出現 `internal-faq-lan` 且狀態為連線成功（綠燈），展開即可檢視共 **11 個可用工具**（完整說明見第 4 節）。
4. *提示*：若透過熱更新**新增或刪減工具**（Tool Schema 變更），需於此頁面重新整理（Restart）`internal-faq-lan`，IDE 才會重新拉取最新工具清單。

---

## 3. Agent 測試提問範例

設定完成後，直接在對話框向 Agent 輸入以下任一指令進行驗證：
- 「幫我確認目前連線到的遠端 MCP Server 主機資訊」
- 「查詢內部知識庫有哪些分類？」
- 「MCP Server 主機有哪些運行中的 IIS / NSSM 服務？」
- 「檢視遠端指定目錄檔案結構，或讀取某個日誌檔最後 50 行的 ERROR 紀錄」
- 「讀取並更新遠端 `faq_data.json` 知識庫內容」

---

## 4. 現存工具說明

目前 `server.py` 共註冊 **11 個 MCP 工具**，依功能分為四大類：

### 4.1 系統狀態與知識庫工具
| 工具名稱 | 主要參數 | 功能說明 |
| :--- | :--- | :--- |
| `get_server_info` | *(無)* | 取得遠端伺服器主機名稱、區網 IP、目前時間、知識庫筆數與支援能力旗標。 |
| `list_faq_categories` | *(無)* | 列出 `faq_data.json` 內部知識庫目前所有分類及各分類筆數。 |
| `search_internal_faq` | `keyword=""`, `category=""` | 依關鍵字（不分大小寫比對問題、回答、分類、標籤）與分類篩選搜尋模擬知識庫；留空回傳全部。 |

### 4.2 IIS / NSSM / Windows 服務與日誌探針工具
| 工具名稱 | 主要參數 | 功能說明 |
| :--- | :--- | :--- |
| `inspect_service` | `service_name` | 檢測指定 Windows 服務、IIS（如 `W3SVC`）或 NSSM 服務的狀態、PID、執行檔路徑、啟動類型及是否為 NSSM 代管。 |
| `list_services` | `filter_keyword=""` | 列出遠端機台 Windows 服務清單，支援關鍵字篩選（上限回傳前 30 筆）。 |
| `inspect_tail_log` | `log_path`, `lines=50`, `filter_keyword=""` | 僅讀取日誌檔末尾 N 行（上限 200 行）並支援關鍵字快篩（如 `ERROR`、`Exception`），避免大檔案消耗過多 Token。 |

### 4.3 通用型遠端檔案系統工具
| 工具名稱 | 主要參數 | 功能說明 |
| :--- | :--- | :--- |
| `read_remote_file` | `file_path`, `max_chars=20000` | 讀取遠端指定文字檔內容（支援相對／絕對路徑），預設上限 20,000 字元。 |
| `write_remote_file` | `file_path`, `content`, `create_backup=True`, `restart_if_server=True` | 通用寫入／更新遠端文字檔，採原子寫入並自動建立 `.bak` 備份；若為 `.json` 會先驗證語法，若為 `server.py` 則自動轉交至安全熱更新流程。 |
| `list_remote_directory` | `dir_path="."` | 查看遠端指定目錄下的檔案與子資料夾清單（含類型、大小與最後更新時間）。 |

### 4.4 專屬安全自身熱更新工具
| 工具名稱 | 主要參數 | 功能說明 |
| :--- | :--- | :--- |
| `apply_server_update` | `new_code` | 安全熱更新 `server.py`：依序執行 AST 語法檢查、子程序探針試跑（Pre-flight Probe）、自動備份 `server.py.bak` 與原子覆寫，並於 1.5 秒後退出交由 `supervisor.py` 自動重啟。 |
| `rollback_server` | *(無)* | 將 `server.py` 手動還原為 `server.py.bak` 備份版本，並於 1.5 秒後觸發重啟生效。 |
