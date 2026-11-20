# 企業內部審計處 — 正式審計工作底稿 (Audit Working Paper)

**底稿編號 (Ref No.)**：`WP-2026-D05-001`  
**專案代碼 (Project ID)**：`PRJ-2026-005`  
**專案名稱 (Project Title)**：雲端混合架構與 Kubernetes 安全審計 (Cloud Hybrid & Kubernetes Security Audit)  
**受查單位 (Auditee)**：雲端維運部 (Cloud Operations Division) / 雲端中心  
**主導稽核員 (Lead Auditor)**：David Wang (資安主任稽核員, CISA, CISSP)  
**覆核主管 (Reviewer)**：Grace Chen (內部稽核長 / Chief Audit Executive, CIA, CISM)  
**稽核期間 (Audit Period)**：2026-05-01 至 2026-06-20  
**底稿編製日期 (Date Prepared)**：2026-06-25 (最新追蹤更新：2026-11-19)  
**機密等級 (Classification)**：【極機密】內部審計專用 (Strictly Confidential - Internal Audit Only)  

---

## 壹、專案審計摘要與基本屬性 (Executive Summary)

### 1.1 專案基本資料卡

| 項目 | 審計登錄內容 | 說明 / 備註 |
| :--- | :--- | :--- |
| **專案編號** | `PRJ-2026-005` | 2026 年度關鍵雲端基礎架構專案審計 |
| **專案名稱** | 雲端混合架構與 Kubernetes 安全審計 | 針對集團生產環境 K8s 容器叢集之專案健檢 |
| **受查部門** | 雲端維運部 (代碼: `D05`) | 隸屬「雲端中心」，現有編制人員 24 人 |
| **主導稽核員** | David Wang | 負責執行現場稽核、技術抽驗與缺失訪談 |
| **稽核執行期間** | 2026-05-01 ～ 2026-06-20 | 歷時 7 週，涵蓋技術測試與架構覆核 |
| **專案狀態** | **Completed (已結案)** | 審計現場作業已完成，現處於缺失改善跟催階段 |
| **總體風險評級** | 🔴 **CRITICAL (重大風險)** | 全組織最高風險等級，具系統性安全威脅 |
| **合規綜合評分** | ⚠️ **65 / 100 分** | 不及格 (門檻 80 分)，全集團部門排名第 7 (墊底) |

### 1.2 部門合規指標與基線對比 (`department_metrics`)

* **2026-Q3 部門合規通過率**：**68.0%**（全集團平均 83.6%，落後 15.6%）。
* **重大缺失數 (Critical Issues)**：**3 項**（全組織最高，佔全集團重大缺失數之 50%）。
* **部門背景綜述**：雲端維運部掌管集團混合雲與 Kubernetes 核心微服務叢集，乘載線上電子商務平台、大數據分析與內部 ERP 總帳系統。其資訊安全水平直接決定全集團系統之存亡，風險外溢效應（Blast Radius）極大。

---

## 貳、審計目標、範疇與依據準據 (Audit Scope & Criteria)

### 2.1 審計目標
1. 查核 Kubernetes 生產叢集節點（Control Plane / Worker Nodes）組態與存取防護。
2. 評估微服務 Pod 工作負載（Workload）安全設定（非 Root 運行、權限提升限制、唯讀檔案系統）。
3. 檢驗容器映像檔（Container Image）生命週期管理與重大弱點（CVE）防堵機制。
4. 查驗生產機敏憑證（Secrets）於靜態存儲、傳輸過程與應用程式掛載時之安全性。

### 2.2 審計準據與標準
* **CIS Kubernetes Benchmark v1.8.0**（特別針對 Section 5: Pod Security Standards）。
* **NIST SP 800-190** (Application Container Security Guide)。
* **OWASP Kubernetes Top 10**（K01: Insecure Workload Configurations, K04: Lack of Centralized Policy Enforcement）。
* **ISO/IEC 27001:2022 控制措施**：
  * A.8.8 管理技術弱點 (Management of technical vulnerabilities)
  * A.8.24 密碼編譯技術之使用 (Use of cryptography)
  * A.8.2 具備特權之存取權限 (Privileged access rights)

---

## 參、審計查核程序與測試取樣 (Testing Methodology & Sampling)

1. **工作負載安全性檢測**：
   * 透過 `kubectl get pods -A -o json` 抽查生產環境 15 個核心微服務工作負載。
   * 比對 `securityContext` 設定，檢查 `runAsNonRoot`、`allowPrivilegeEscalation`、`readOnlyRootFilesystem`。
2. **映像檔弱點掃描**：
   * 抽驗目前正在運行的微服務 Base Images，執行靜態 CVE 弱點探測與比對。
3. **機密資料儲存檢查**：
   * 抽查 10 個核心資料庫連線 ConfigMap 與 Kubernetes 原生 Secret 物件。
   * 比對是否已整合外部企業級硬體安全模組 (HSM) 或金鑰保管庫 (Vault)。

---

## 肆、詳細審計發現與缺失評估表 (Audit Findings & Evaluation - 5C Model)

本專案共查得 **2 項重大與高度資安缺失**，整體缺失等級結構如下：

### 4.1 缺失一：Kubernetes 容器叢集運行 Root 權限且存在漏洞 (`FND-107`)

| 缺失屬性 | 查核登錄內容 |
| :--- | :--- |
| **缺失編號** | `FND-107` |
| **所屬類別** | 資安防護 (Security Defense) |
| **嚴重等級** | 🔴 **Critical (重大)** |
| **發現日期** | 2026-05-10 |
| **原訂改善期限** | **2026-06-30** |
| **當前處理狀態** | 🚨 **Open (未修復 — 目前已嚴重逾期！)** |

#### 5C 深入分析：
* **【現況 Condition】**：抽查 15 組生產核心微服務容器，發現高達 11 組容器以 `root`（UID 0）身分執行，且 Deployment YAML 檔中完全未宣告 `securityContext.runAsNonRoot: true`。此外，微服務所使用的 Base Docker Image 長達 8 個月未更新，內建函式庫含有已知重大漏洞 **CVE-2025-XXXX (CVSS 9.8，具備 RCE 遠端代碼執行能力)**。
* **【準據 Criteria】**：CIS Kubernetes Benchmark 5.2.6 明確要求「Ensure that containers are not running with root user」；NIST SP 800-190 Section 3.1 要求強制阻斷含高危 CVE 映像檔部署。
* **【成因 Cause】**：微服務開發團隊為求初期部署便利，直接沿用官方預設之全權限映像檔；CI/CD 流程缺乏自動化弱點掃描閘門，維運團隊亦未落實定期 Patch 週期。
* **【衝擊 Consequence】**：攻擊者一旦利用微服務應用層漏洞入侵容器，即可藉由容器內部的 Root 權限輕易穿透容器隔離牆（Container Escape），控制底層 Linux 宿主節點（Node），進而橫向移動接管整個 K8s Control Plane 與全行核心業務系統。
* **【審計建議措施 Corrective Action】**：
  1. 於 Kubernetes 叢集強制實施 **Pod Security Standards (PSS) Restricted 級別**，禁止任何以 UID 0 運行的 Workload 啟動。
  2. 微服務 Dockerfile 全面改採 Alpine 或 Google Distroless 最小化映像檔，並建立特定非特權使用者（如 `UID: 10001`）。
  3. 於 GitLab CI / GitHub Actions Pipeline 中強制部署 Trivy / Grype 弱點掃描，凡含有 CVSS 7.0 以上未修補漏洞者嚴格阻斷發佈。

---

### 4.2 缺失二：K8s Secrets 儲存明文密碼未整合 Vault (`FND-108`)

| 缺失屬性 | 查核登錄內容 |
| :--- | :--- |
| **缺失編號** | `FND-108` |
| **所屬類別** | 存取控制 (Access Control) |
| **嚴重等級** | 🟠 **High (高風險)** |
| **發現日期** | 2026-05-15 |
| **原訂改善期限** | **2026-07-15** |
| **當前處理狀態** | 🔵 **Verifying (驗證中)** |

#### 5C 深入分析：
* **【現況 Condition】**：微服務連線至生產環境 PostgreSQL 與 Redis 的帳號密碼、連線字串，直接以 Base64 編碼存放在原生 ConfigMap 與 Kubernetes Secret 物件中；叢集並未啟用 etcd 靜態加密 (EncryptionConfiguration)。
* **【準據 Criteria】**：ISO/IEC 27001:2022 控制措施 A.8.24 要求敏感機密資料於靜態與傳輸皆需加密保管；CIS Benchmark 5.4.1 要求金鑰管理需具備獨立集中式儲存與自動輪替機制。
* **【成因 Cause】**：系統初期建置時為加速時程，誤將 Base64 編碼等同於加密機制，未依架構規範整合企業外部金鑰管理平台。
* **【衝擊 Consequence】**：Base64 僅為編碼格式，任何人皆能以單一指令逆向還原出明文密碼。任何具備 Namespace 讀取權限之開發維運人員、或取得 Node 權限之惡意程式，皆可輕鬆擷取核心資料庫最高權限帳密，導致全集團客戶個資與交易紀錄面臨洩漏風險。
* **【審計建議措施 Corrective Action】**：
  1. 全面建置企業級 HashiCorp Vault / Cloud KMS 平台作為單一信任來源。
  2. 叢集端導入 **External Secrets Operator (ESO)** 或 **Secrets Store CSI Driver**，於 Pod 啟動時動態注入短效憑證，嚴格禁止靜態儲存帳密。
  3. 實施資料庫連線密鑰每 90 天自動輪替機制，並啟用 etcd 本地金鑰靜態加密。

---

## 伍、改善處置追蹤與緊急跟催狀態 (Remediation Tracking)

截至本次審計工作底稿追蹤基準日（2026-11-19），缺失追蹤狀態彙整如下：

| 缺失編號 | 缺失標題 | 風險等級 | 原訂改善到期日 | 目前狀態 | 改善成本 (TWD) | 審計追蹤意見與跟催結論 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **FND-107** | 容器叢集運行 Root 且存在 CVE 漏洞 | **Critical** | 2026-06-30 | 🚨 **Open** | 估計 150,000 | **【嚴重逾期】** 已逾期超過 4 個月！雲端維運部因擔心影響線上微服務穩定性而延宕修復。稽核處已發出《重大逾期限期改善通知書》，限於 14 日內提交補正變更計畫。 |
| **FND-108** | K8s Secrets 儲存明文密碼未整合 Vault | **High** | 2026-07-15 | 🔵 **Verifying** | 估計 200,000 | **【驗證中】** 雲端維運部已於 UAT 測試叢集完成 Vault 與 ESO 整合 POC，目前正在進行生產環境微服務遷移測試，預計於近期提報複查驗證。 |

---

## 陸、綜合審計意見與後續複核計畫 (Audit Opinion & Sign-off)

### 6.1 總體審計結論
本案專案合規評分僅為 **65 分**，總體風險判定為 **CRITICAL（重大）**。  
受查單位雲端維運部在 Kubernetes 容器化部署與雲端基礎設施維運中，存在嚴重之特權配置不當、已知漏洞未修及明文金鑰暴露等重大缺陷。考量到該叢集承載集團核心業務，防線失守將導致毀滅性災難，**審計處正式給予「附條件嚴重改善意見」，並將雲端維運部列入全集團第 1 優先資安加強輔導與重點列管對象**。

### 6.2 後續管制作業
1. **緊急升級會議**：稽核長將於本週親自召集雲端維運部主管與技術負責人召開專案改善跟催協調會。
2. **2026-Q4 專案複查**：將 `PRJ-2026-005` 改善成效納入 2026-Q4 首要專案複查項目，未完成改善前暫緩該部門年度資安合規獎勵發放。

### 6.3 簽核與核准紀錄

| 簽核角色 | 職稱 / 姓名 | 專業資格 | 簽名 / 蓋章 | 審核日期 | 審核結果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **底稿編製人** | 資安稽核專員 / **David Wang** | CISA, CISSP | *David Wang (Signed)* | 2026-06-25 | 查核屬實，送覆核 |
| **底稿覆核人** | 稽核主管 / **Grace Chen** | CIA, CISM | *Grace Chen (Signed)* | 2026-06-28 | 審核無誤，列管跟催 |
| **審計核准長官** | 集團總稽核 / **Chief Auditor** | CIA, CPA | *Chief Auditor (Signed)* | 2026-06-30 | 核准結案，通報董事會 |
