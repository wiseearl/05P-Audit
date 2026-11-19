# 區網遠端維運與內部知識庫 MCP Server (MCP v2)

本專案用於在區網另一台機器架設 **Streamable HTTP MCP Server**，供本地 Antigravity IDE Agent 跨機連線呼叫，具備**企業內部模擬知識庫查詢**、**IIS / NSSM / Windows 服務狀態與日誌探針**、**通用遠端檔案讀寫**、**多軌分類日誌與成本審計**，以及**安全自身熱更新（Self-Update）與災難還原**能力。

## 檔案與目錄架構

- `server.py`：以 MCP v2 `MCPServer` + `uvicorn` 實作的 Streamable HTTP MCP 主程式（預設監聽 `0.0.0.0:8000/mcp`，採用收斂單一網關架構 `remote_audit_gateway`）。
- `supervisor.py`：Python 原生守護行程（Supervisor），負責支援完整 UTF-8 輸出、偵測 `Exit Code 0` 自動熱重啟，以及連續異常崩潰 3 次自動以 `server.py.bak` 還原。
- `run_server.bat`：Windows 一鍵啟動腳本（切換 UTF-8 `chcp 65001` 後啟動 `supervisor.py`）。
- `install_service.bat`：Windows 服務一鍵安裝腳本（自動偵測 NSSM，若本機無則從 NSSM 官網自動下載並驗證 SHA-256；鎖定 Python 實體絕對路徑並註冊常駐服務 `MCP_Server_Johnson`，輸出日誌導流至 `logs\nssm_*.log`）。
- `uninstall_service.bat`：Windows 服務一鍵卸載腳本（雙向停止並徹底清除 NSSM 服務）。
- `nssm/`：專案專屬 NSSM 目錄（已列入 `.gitignore` 不入庫；執行 `install_service.bat` 時自動從官網下載放置 `nssm.exe`，離線環境亦可手動放入）。
- `faq_data.json`：模擬企業內部知識庫資料（每次工具呼叫會即時讀取，修改後無須重啟 Server）。
- `logs/`：多軌分類運行日誌與計費審計目錄（自動建立）：
  - `lifecycle.log`：伺服器啟動時間、PID、連接埠、排程重啟與版本重載等生命週期事件。
  - `audit_tools.jsonl`：逐筆呼叫結構化紀錄（時間戳記、耗時、輸入/輸出字元、預估 Token 與成本、去機密化參數）。
  - `errors.log`：例外堆疊追蹤、錯誤摘要與排查上下文。
  - `daily_stats.json`：每日彙總統計（本日呼叫次數、各 Action 分佈、Token 消耗、累積節省的 Schema Token 與開機時間）。
- `.env.example`：環境變數與 LINE Messaging API 憑證範本（部署時請複製為 `.env` 並填入實際值，`.env` 不會進入 Git）。
- `requirements.txt`：Python 相依套件清單（`mcp>=2.0.0`、`httpx>=0.27.0`）。
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
   - 透過 `run_server.bat` / `supervisor.py` 啟動，才能支援熱更新的**自動重啟**與連續崩潰自動還原（`server.py.bak`）。
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
1. 在 Antigravity IDE 對話窗口左上 Toggle Sidebar 中開啟 **Customizations > Installed**。
2. 找到 **MCP Servers**。
3. 確認列表中出現 `internal-faq-lan` 且狀態為連線成功（綠燈），此時可見僅有 **1 個收斂網關工具：`remote_audit_gateway`**。
4. *提示*：若遠端伺服器由舊版 12 工具升級為單一網關工具，需於 IDE 介面點擊重新整理（Restart）`internal-faq-lan`，IDE 才會重新拉取最新工具清單。

---

## 3. Agent 提問與呼叫範例

在對話中 Agent 會自動透過 `remote_audit_gateway` 調用對應功能，使用者亦可直接以自然語言下達指令：
- 「幫我確認目前遠端主機的硬體與 MCP 伺服器運行狀態」
- 「檢視今日 MCP 伺服器的呼叫統計與預估花費」
- 「查詢內部知識庫關於 VPN 或打卡的規範」
- 「檢查遠端機台的 <目標服務名稱> 背景服務是否正常運行」
- 「查看服務日誌最後 50 行，過濾是否有 ERROR」
- 「檢查今日系統執行進度，整理成重點摘要推播至 LINE 通知」

---

## 4. 單一收斂網關工具架構 (`remote_audit_gateway`)

為了解決傳統 MCP 將多個工具分散註冊時，每個工具綱要（Tool Schema）在**每一回合對話**都會被完整帶入 LLM System Prompt 造成巨大 Token 浪費與思維分散的問題，本專案全面升級為**統一網關設計（Gateway Pattern）**：

> [!TIP]
> **Prompt Token 開銷減少 >90%**：
> - 舊架構：12 個工具獨立註冊，每回合對話消耗約 **2,000 Prompt Tokens**。
> - 新架構：僅註冊 1 個 `remote_audit_gateway`，每回合對話僅消耗約 **180 Prompt Tokens**。
> - 每次對話現省約 **1,820 Tokens**，大幅提升 Agent 思考速度與專注度。

### 支援之 Actions 完整清單

網關工具簽名：`remote_audit_gateway(action: str, params: dict | None = None)`

| 分類 | 動作名稱 (action) | 別名 (aliases) | 參數格式 (params) | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| **系統與統計** | `server_info` | `get_server_info`, `info` | *(無或留空)* | 取得主機名稱、IP、目前時間、開機時間、運行秒數與支援能力旗標。 |
| | `audit_stats` | `get_audit_stats`, `stats` | `{"target_date": "YYYY-MM-DD"}` (選填) | 查詢指定日期或今日的工具調用次數、各動作分佈、Token 開銷與節省量。 |
| **內部知識庫** | `list_faq_categories` | `faq_categories`, `categories` | *(無)* | 列出內部知識庫所有分類及各分類筆數。 |
| | `search_internal_faq` | `search_faq`, `faq` | `{"keyword": "...", "category": "..."}` | 依關鍵字與分類篩選內部知識庫（比對問題、回答、分類、標籤）。 |
| **服務與日誌** | `inspect_service` | `service` | `{"service_name": "W3SVC"}` (必填) | 檢測指定 Windows 服務、IIS 站台或 NSSM 服務的運行狀態、PID 與啟動路徑。 |
| | `list_services` | `services` | `{"filter_keyword": "<服務名稱關鍵字>"}` (選填) | 列出 Windows 服務清單（支援關鍵字快速篩選）。 |
| | `inspect_tail_log` | `tail_log`, `log` | `{"log_path": "...", "lines": 50, "filter_keyword": "ERROR"}` | 高效讀取末尾 N 行日誌（預設 50，上限 200），**內建機密檔案黑名單保護**。 |
| **通用檔案** | `read_remote_file` | `read_file`, `read` | `{"file_path": "...", "max_chars": 20000}` | 讀取遠端文字檔（上限 20,000 字元），**禁止讀取 `.env` 與私鑰/憑證**。 |
| | `write_remote_file` | `write_file`, `write` | `{"file_path": "...", "content": "...", "create_backup": true}` | 原子寫入文字檔，JSON 自動語法校驗，寫入 `server.py` 自動轉交安全熱更新。 |
| | `list_remote_directory` | `list_dir`, `ls` | `{"dir_path": "."}` | 查看遠端目錄結構（含大小、修改時間）。 |
| | `delete_remote_file` | `delete_file`, `delete`, `rm` | `{"file_path": "..."}` | 刪除遠端檔案，**內建 `.env`、私鑰與關鍵系統檔案防刪除黑名單保護**。 |
| **熱更新還原** | `apply_server_update` | `apply_update`, `update` | `{"new_code": "..."}` (必填) | AST 語法檢查 + 子程序探針試跑 + `.bak` 自動備份，1.5 秒後優雅重啟。 |
| | `rollback_server` | `rollback` | *(無)* | 將程式碼還原為前一版 `server.py.bak` 備份並自動重啟。 |
| **外部告警** | `send_line_message` | `send_line`, `line` | `{"message": "...", "to_id": "..."}` | 透過 LINE Push API 推播去識別化摘要（上限 1,500 字），**內建 DLP 機密攔截**。 |

---

## 5. 多軌分類日誌與成本審計架構

伺服器具備多軌即時日誌與統計機制，所有日誌檔均保存在專案目錄下的 `logs/` 資料夾：

1. **`lifecycle.log`（伺服器生命週期紀錄）**：
   - 記錄伺服器每次 Boot 時間、PID、連線 Host/Port、Python 版本。
   - 記錄每次排程重啟事件（如 `apply_server_update`、`rollback_server`）與延遲時間。
2. **`audit_tools.jsonl`（工具調用結構化紀錄）**：
   - 每一筆呼叫寫入一行 JSON，包含：精確毫秒級執行時間 (`elapsed_ms`)、成功狀態、輸入輸出字元數與預估 Token、預估呼叫動態花費 (`cost_usd`)。
   - 自動將參數中包含 `token`、`password`、`key`、`secret`、`content` 等欄位去識別化遮罩，防範紀錄檔自身洩密。
3. **`errors.log`（異常與錯誤排查日誌）**：
   - 記錄執行期間所有捕捉之例外，包含時間戳記、調用動作、例外類型、錯誤訊息、上下文與完整 Python 堆疊追蹤。
4. **`daily_stats.json`（每日彙總統計檔案）**：
   - 依日期索引聚合當日總開機次數、累積呼叫次數、各 Action 調用次數分佈、輸入/輸出字元與 Token 總量、預估花費，以及**因收斂為單一網關而省下的 System Prompt Token 總量**。
   - 可透過 `remote_audit_gateway(action="audit_stats")` 隨時遠端查詢。

---

## 6. 開機常駐服務選型：NSSM vs IIS 評估

在將 MCP Server 由手動 `.bat` 執行改為開機自動常駐服務時，經深度評估確認**採用 NSSM 為最佳方案**，**不建議採用 IIS**：

### 評估對比矩陣

| 評估面向 | NSSM (Non-Sucking Service Manager) *(建議方案)* | IIS (Internet Information Services) + ARR |
| :--- | :--- | :--- |
| **架構契合度** | **最佳**：原生支援直接將任何 CLI/Python 程式註冊為 Windows Service。 | **複雜**：IIS 本質為 Web 伺服器，需額外安裝 URL Rewrite、ARR 模組反向代理。 |
| **串流 (SSE) 支援** | **天然支援**：MCP v2 Streamable HTTP 透過 Uvicorn 原生處理 chunked streaming，零干擾。 | **易遭緩衝**：IIS 反向代理預設對 HTTP 回應實施 Response Buffering，常導致串流被截斷或延遲。 |
| **熱更新重啟相容** | **原生契合**：`supervisor.py` 原生處理重啟與還原，NSSM 負責外層保活，雙層容錯極為穩固。 | **權限衝突**：IIS Application Pool 權限（`IIS_IUSRS`）受限，熱更新複寫檔案容易遭遇拒絕存取。 |
| **現有環境一致性** | **完全一致**：既有背景常駐服務多採用 NSSM 託管，便於統一維運管理。 | **額外負擔**：需要額外維護 IIS 站台、Bindings 與 Application Request Routing 規則。 |

---

## 7. 背景靜態零花費保證 (Zero Static Cost Guarantee)

本 MCP Server 在常駐運行時保證滿足**完全零靜態花費**：

1. **Token 花費保證為 $0.00**：
   - 伺服器是純粹被動的 HTTP 監聽服務，在沒有 Agent 發起 HTTP 請求時，僅處於作業系統核心層級的 Socket 事件等待狀態（`asyncio` epoll/IOCP event loop）。
   - 伺服器不會自行呼叫任何外部 LLM API、不會進行後台定時推論，閒置期間產生的 API Token 消耗為 **0 Tokens**。
2. **硬體開銷極低**：
   - 閒置時 CPU 使用率為 **0.0%**。
   - 記憶體常駐佔用約 **35 MB ~ 50 MB**，對主機資源影響幾可忽略。

---

## 8. 區網 IP 嚴格白名單與 .env 動態即時生效 (Zero-Trust & Live Reload)

本伺服器在網路中介層實施**嚴格零信任（Zero-Trust）白名單控制**：

1. **未設定 `.env` 時**：僅允許本機（`127.0.0.1` / `::1`）與伺服器自身 IP 連線，**所有外部區網連線一律直接回傳 `403 Forbidden` 拒絕存取**。
2. **設定方式**：在遠端專案目錄下複製 `.env.example` 為 `.env`，設定允許連線之客戶端 IP：
   ```env
   MCP_ALLOWED_IPS=<允許連線的客戶端IP>
   ```
3. **動態即時生效（Live Reload，免重啟）**：
   - 伺服器在每次收到請求時，皆即時動態讀取 `.env` 檔案。
   - **修改 `.env` 存檔後立即生效**，**不需要手動重啟 NSSM 服務，更不需要重新安裝**。

---

## 9. 工作區隔離設定指南 (Workspace Isolation Guide)

當前本 MCP Server 註冊於使用者全域設定（`~/.gemini/config/mcp_config.json`）。若您在其他專案中不想讓 Agent 看到或連線此工具，未來可透過以下方式進行工作區隔離：

### 方式一：全域一鍵開關（最簡單）
在不需要使用本服務的工作期間，在 `%USERPROFILE%\.gemini\config\mcp_config.json` 中加上 `"disabled": true` 即可：
```json
{
  "mcpServers": {
    "internal-faq-lan": {
      "url": "http://<遠端機台區網IP>:8000/mcp",
      "disabled": true
    }
  }
}
```

### 方式二：專案級工作區隔離（Project-Scoped Plugin）
若僅希望在特定專案中啟用此 MCP 工具，可在該專案根目錄建立專屬外掛設定檔 `.gemini\plugin.json`：
```json
{
  "name": "<專案專屬外掛名稱>",
  "version": "1.0.0",
  "mcpServers": {
    "internal-faq-lan": {
      "url": "http://<遠端機台區網IP>:8000/mcp"
    }
  }
}
```
並自全域 `mcp_config.json` 中移除 `internal-faq-lan`。如此一來，只有在開啟該專案工作區時，Agent 才會載入此 MCP Server。
