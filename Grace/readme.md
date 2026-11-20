# 智慧稽核資料庫分析與視覺化 MCP Server (Audit Analytics MCP)

本專案為獨立開發的 **Streamable HTTP MCP Server**，專門針對**企業內部稽核（Audit）、資安合規性分析與資料庫視覺化洞察**打造。  
支援透過區網或虛擬機（VM）跨機連線，讓本地的 **Antigravity IDE Agent** 具備安全查庫、統計剖析與動態生成 Mermaid 視覺化圖表的能力。

---

## 🌟 核心特色與價值

1. **專業業務場景定位（與系統維運完全區隔）**：
   - 聚焦於**稽核項目管理、資安缺失追蹤、部門合規評分與改善處置分析**。
2. **極致安全防護（唯讀保證）**：
   - 內建 `safe_sql_query` 安全檢查機制，嚴格阻絕 `DROP`、`DELETE`、`UPDATE`、`INSERT` 等破壞性語法，僅允許安全 `SELECT` 查詢。
3. **原生視覺化（Mermaid 圖表自動生成）**：
   - 內建 `generate_mermaid_chart` 工具，AI 查完資料後能自動轉譯為 Mermaid 圓餅圖與長條圖，直接在 Antigravity 的對話框或 Artifacts 呈現。
4. **零外部依賴、輕量好部署**：
   - 以 Python 原生 SQLite 為資料存儲，免架設重量級資料庫，內建擬真樣本資料庫，開箱即用。

---

## 📂 檔案架構

- `server.py`：以 MCP v2 `MCPServer` + `uvicorn` 實作的 Streamable HTTP 主程式（預設監聽 `0.0.0.0:8001/mcp`）。
- `db_init.py`：資料庫初始化與擬真稽核種子資料生成腳本。
- `audit_analytics.db`：內建 SQLite 稽核資料庫（含專案、缺失、指標與改善處置 4 張資料表）。
- `requirements.txt`：Python 相依套件清單（`mcp>=2.0.0`, `uvicorn>=0.30.0`）。
- `run_server.bat`：Windows / VM 一鍵啟動批次檔（自動配置 UTF-8 編碼）。
- `mcp_config.example.json`：本地 Antigravity 連線設定範本。

---

## 📊 內建資料表結構

| 資料表名稱 | 欄位說明 | 業務代表意義 |
| :--- | :--- | :--- |
| `audit_projects` | `id, project_name, department, lead_auditor, start_date, end_date, overall_risk, score, status` | 稽核專案總覽（含風險等級、評分與負責人） |
| `audit_findings` | `id, project_id, category, severity, title, description, status, finding_date, remediation_due` | 稽核發現的缺失（包含資安防護、存取控制、隱私合規等） |
| `department_metrics` | `dept_id, dept_name, branch, staff_count, passing_rate, critical_issues, audit_quarter` | 各部門每季合規通過率與重大缺失數 |
| `remediation_records` | `id, finding_id, action_taken, verified_by, completed_date, cost_twd` | 缺失改善方案、複查人員與改善成本 (TWD) |
| `hr_employees` | `emp_id, emp_name, department, email, id_card, bank_account, phone, status, hire_date, term_date` | **HR 人資員工主檔**（工號、姓名、銀行帳戶、電話、在職狀態、離職生效日） |
| `erp_vendors` | `vendor_id, vendor_name, tax_id, bank_account, contact_person, phone, address, status` | **ERP 供應商廠商主檔**（統編、銀行帳戶、聯絡人、電話、公司登記地址） |
| `procurement_orders` | `po_id, po_date, vendor_id, buyer_emp_id, department, amount_twd, item_description, status, approver` | **採購訂單記錄**（訂單編號、日期、金額、品項規格、承辦人、核決層級主管） |
| `system_access_logs` | `log_id, access_time, emp_id, action_type, source_ip, system_name, result` | **核心系統存取軌跡**（日誌 ID、時間戳記、存取系統、外部/內部 IP、匯出資料行為） |
| `expense_claims` | `claim_id, claim_date, emp_id, invoice_no, amount_twd, purpose, status` | **費用報銷單明細**（請款單號、請款人、統一發票字軌號碼、金額、報銷用途） |

---

## 🛠️ 現有 MCP 工具清單 (共 12 個)

### 4.1 資料庫分析與視覺化工具 (方案 B)
| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `get_db_overview` | *(無)* | 取得資料庫檔案大小、資料表清單與各表總筆數。 |
| `get_table_schema` | `table_name=""` | 取得指定資料表（或全部表）的詳細欄位型態、主鍵與 DDL 語法。 |
| `safe_sql_query` | `query`, `max_rows=100` | 安全執行唯讀 SQL 查詢，自動計算執行耗時（ms）並回傳結構化資料。 |
| `get_table_profile` | `table_name` | 快速對資料表進行數據探測（欄位數量、空值 Null 統計、前 3 筆樣本資料）。 |
| `generate_mermaid_chart` | `chart_type`, `title`, `sql_query` | 執行 SQL 查詢並直接轉譯為 Antigravity 支援的 Mermaid 長條圖 (`bar` / `xychart-beta`) 或正宗圓餅圖圖片 Markdown。 |
| `export_svg_pie_chart` | `title`, `sql_query`, `filename="audit_pie_chart.svg"` | **正宗圓形餅圖**：執行 SQL 並純 Python 離線渲染輸出漂亮的向量 SVG 圓形圓餅圖，無須聯網。 |
| `reset_sample_database` | *(無)* | 將資料庫重新重置回預設的種子資料狀態。 |

### 4.2 API 規格合規與智慧測資檢驗工具 (方案 C)
| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `get_api_spec_endpoints` | `spec_path=""` | 自動解析 OpenAPI / Swagger 規格檔，列出所有 API 路徑、HTTP 方法與 Request Schema。 |
| `generate_smart_mock_data` | `schema_name`, `scenario="normal"` | **智慧測資生成器**：支援 `normal` (正常)、`boundary` (邊界極限值) 與 `malicious` (惡意/注入/格式錯誤) 三種情境。 |
| `validate_api_contract` | `schema_name`, `payload` | **契約合規檢查員**：自動比對資料是否符合 OpenAPI 規範（檢查必填欄位、型態、min/max、enum、正則 pattern）。 |

### 4.3 審計工作底稿與正式報告自動生成工具
| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `generate_audit_working_paper` | `project_id`, `output_format="both"` | **一鍵產出正式工作底稿**：自動抓取專案與缺失資料，輸出符合國際稽核標準之 Markdown (`.md`) 與排版精美的 Microsoft Word (`.docx`) 底稿！ |

### 4.4 全量跨系統交叉比對與舞弊偵測工具 (Cross-System Fraud Detection)
| 工具名稱 | 參數 | 功能說明 |
| :--- | :--- | :--- |
| `run_fraud_detection` | `rule_filter="all"` | **全量跨系統碰撞分析**：比對 HR、ERP 供應商、採購訂單、存取日誌與費用報銷，自動偵測利益衝突、化整為零拆單、離職幽靈帳號與重複報銷發票，產出具備稽核改善建議與證據鏈之完整分析報告。 |

---

## 🚀 部署步驟（虛擬機 VM 或實體伺服器）

### 步驟 1：安裝相依套件
在 VM 的終端機中執行：
```bash
cd D:\GitHub\05P-Audit\Grace
pip install -r requirements.txt
```

### 步驟 2：開放 VM 防火牆 Port 8001
在 VM 中以系統管理員身分開啟 PowerShell 執行：
```powershell
New-NetFirewallRule -DisplayName "MCP Server 8001" -Direction Inbound -LocalPort 8001 -Protocol TCP -Action Allow
```

### 步驟 3：啟動 MCP 服務
雙擊執行 `run_server.bat`，或在終端機中執行：
```bash
python server.py
```
> 啟動後終端機將顯示服務位址，例如：`http://192.168.x.x:8001/mcp`。

---

## 🔌 本地 Antigravity 連線設定

1. 打開本地電腦的設定檔：`%USERPROFILE%\.gemini\config\mcp_config.json`
   *(即 `C:\Users\<使用者名稱>\.gemini\config\mcp_config.json`)*
2. 填入 VM 的 IP 位址與 `8001` 連接埠：
   ```json
   {
     "mcpServers": {
       "grace-audit-suite": {
         "url": "http://<你的VM_IP>:8001/mcp"
       }
     }
   }
   ```
3. 在 Antigravity IDE 側邊欄檢查 **Customizations > Installed > MCP Servers**，確認顯示綠燈即連線成功！

---

## 🎤 向組長 Demo 的實戰測試 Prompt 與演練劇本

連線成功後，直接在 Antigravity 對話框複製以下 Prompt 進行展示：

### 測試 1：探索資料庫 (方案 B)
> 「請幫我查看目前稽核資料庫有哪些資料表，並說明各表的用途。」

### 測試 2：自然語言複合查庫與缺失分析 (方案 B)
> 「請幫我查詢目前尚未修復（Status 不為 Remediated）且嚴重等級為 Critical 與 High 的缺失清單，並依所屬部門與專案整理成表格回報。」

### 測試 3：動態圖表生成 (方案 B 視覺化)
> 「請幫我調用圖表工具，畫出『各部門合規通過率』的長條圖，以及『各風險等級缺失分佈』的圓餅圖，並綜合分析哪一個部門需要最優先進行資安加強輔導。」

### 測試 4：查看系統 API 規格 (方案 C)
> 「請幫我查看目前系統定義了哪些 API 規格與請求架構？」

### 測試 5：智慧測資生成與合規防禦檢驗 (方案 C)
> 「請針對報銷申請 API（ReimbursementRequest）生成一組 malicious 惡意測資，並使用契約驗證工具檢查該測資違背了哪些規範。」

### 測試 6：一鍵自動生成標準稽核工作底稿 (Word & Markdown)
> 「請幫我產出專案『PRJ-2026-005』（雲端維運部 Kubernetes 安全審計）的正式審計工作底稿，包含 Markdown 與 Word 格式。」

### 測試 7：全量「跨系統交叉比對」與舞弊偵測 (全方位內控防禦)
> 「請幫我執行全量『跨系統交叉比對與舞弊偵測』，分析是否有利益衝突、採購拆單、離職帳號存取或重複報銷等舞弊紅旗，並整理出高風險異常清單與具體事證。（注意：如需視覺化，請以長條圖 xychart-beta 或流程圖 flowchart LR 呈現分佈，請勿使用未支援的 Mermaid pie 語法）」

---

### 3 分鐘 Demo 簡報講稿範例：
1. **開場痛點（30秒）**：「過去長官要看合規與稽核數據，需要請工程師下 SQL 或手動拉 Excel 製圖；而舞弊調查更需要跨 HR、ERP、簽核系統人工肉眼對帳，費時數週且易有疏漏。」
2. **MCP 全功能架構（30秒）**：「Grace 的 MCP 伺服器整合了『數據探測與圖表 (方案 B)』、『API 契約品質檢驗 (方案 C)』、『標準工作底稿生成』以及『全量跨系統舞弊碰撞分析』，一站式支援審計全流程。」
3. **現場展示（90秒）**：
   - 自然語言對話查庫與 Mermaid/SVG 圖表動態繪製。
   - 快速驗證 API 規格與智慧邊界測資防禦。
   - 一鍵秒級導出主管最愛的 IIA 標準 Word 審計工作底稿。
   - 執行全量舞弊比對，幾秒內即刻抓出利益衝突員工、同日拆單避審、離職員工登入與假發票重複請款！
4. **效益總結（30秒）**：「這套結合證實了 Antigravity 搭配 MCP，不僅能做純程式開發，還能直接升級成企業專屬的商業、風控與資安決策助手！」

---

## ❓ 常見問題與排錯指南 (Troubleshooting)

### Q: 為什麼前端畫面偶爾會跳出 `⚠️ Failed to render Mermaid diagram: Invalid mermaid header: "pie title ..."`？
- **原因**：Antigravity 內建的 Markdown 引擎僅支援 `flowchart / graph`, `stateDiagram-v2`, `sequenceDiagram`, `classDiagram`, `erDiagram`, `xychart-beta`，**尚未支援** Mermaid 原生的 `pie` 圓餅圖語法。當 AI 模型主動想用 Mermaid 畫圓餅圖時便會報錯。
- **解法**：
  1. **提問約束**：提問時加上「若需圖表請使用長條圖或表格，避免使用 Mermaid pie」。
  2. **正宗圓餅圖**：請呼叫 `export_svg_pie_chart` 輸出向量 SVG 檔，或調用 `generate_mermaid_chart(chart_type='pie', ...)` 取得 QuickChart 圖片 Markdown。