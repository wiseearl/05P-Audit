"""Database Initializer & Seed Data for Audit Analytics MCP.

建立專門為稽核（Audit）、資安與合規分析設計的 SQLite 資料庫與擬真樣本資料。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "audit_analytics.db"


def init_database(db_path: Path = DB_FILE, force_recreate: bool = False) -> None:
    """初始化並寫入擬真稽核分析資料。"""
    if db_path.exists() and not force_recreate:
        return

    if force_recreate and db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. 建立專案總覽資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_projects (
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        department TEXT NOT NULL,
        lead_auditor TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        overall_risk TEXT NOT NULL, -- Low, Medium, High, Critical
        score INTEGER NOT NULL,      -- 0 ~ 100
        status TEXT NOT NULL         -- In-Progress, Completed, Reviewing
    );
    """)

    # 2. 建立缺失紀錄資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_findings (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        category TEXT NOT NULL,     -- 資安防護, 存取控制, 隱私合規, 營運流程, 資料備份
        severity TEXT NOT NULL,     -- Critical, High, Medium, Low
        title TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL,        -- Open, Remediated, Accepted_Risk, Verifying
        finding_date TEXT NOT NULL,
        remediation_due TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES audit_projects (id)
    );
    """)

    # 3. 建立部門合規指標資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS department_metrics (
        dept_id TEXT PRIMARY KEY,
        dept_name TEXT NOT NULL,
        branch TEXT NOT NULL,        -- 台北總部, 台中分處, 高雄分處, 雲端中心
        staff_count INTEGER NOT NULL,
        passing_rate REAL NOT NULL,  -- 通過百分比 (0.0 ~ 100.0)
        critical_issues INTEGER NOT NULL,
        audit_quarter TEXT NOT NULL  -- 2026-Q1, 2026-Q2, 2026-Q3, 2026-Q4
    );
    """)

    # 4. 建立改善處置追蹤資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS remediation_records (
        id TEXT PRIMARY KEY,
        finding_id TEXT NOT NULL,
        action_taken TEXT NOT NULL,
        verified_by TEXT NOT NULL,
        completed_date TEXT,
        cost_twd INTEGER DEFAULT 0,
        FOREIGN KEY (finding_id) REFERENCES audit_findings (id)
    );
    """)

    # 寫入擬真樣本資料 (Audit Projects)
    projects_data = [
        ("PRJ-2026-001", "2026 Q1 全集團核心系統資安健檢", "資訊科技處", "Grace Chen", "2026-01-10", "2026-02-15", "Medium", 84, "Completed"),
        ("PRJ-2026-002", "線上電商交易平台個資法合規審查", "電子商務部", "David Wang", "2026-02-01", "2026-03-10", "High", 72, "Completed"),
        ("PRJ-2026-003", "財務會計總帳系統權限與審計軌跡稽核", "財務會計處", "Grace Chen", "2026-03-01", "2026-04-05", "Low", 95, "Completed"),
        ("PRJ-2026-004", "客戶服務中心通話與日誌留存查核", "客戶服務部", "Sarah Lin", "2026-04-10", "2026-05-12", "Medium", 81, "Completed"),
        ("PRJ-2026-005", "雲端混合架構與 Kubernetes 安全審計", "雲端維運部", "David Wang", "2026-05-01", "2026-06-20", "Critical", 65, "Completed"),
        ("PRJ-2026-006", "人力資源薪資系統特權帳號盤點", "人力資源處", "Sarah Lin", "2026-07-01", None, "Low", 89, "In-Progress"),
        ("PRJ-2026-007", "2026 Q3 供應商存取通道合規複查", "資訊科技處", "Grace Chen", "2026-08-15", None, "High", 76, "Reviewing"),
    ]
    cursor.executemany(
        "INSERT INTO audit_projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        projects_data
    )

    # 寫入擬真缺失資料 (Audit Findings)
    findings_data = [
        ("FND-101", "PRJ-2026-001", "存取控制", "High", "特權管理員未強制啟用多因素驗證 (MFA)", "內部有 4 組網域管理員帳號僅使用靜態密碼，未綁定 Authenticator 或硬體金鑰。", "Remediated", "2026-01-18", "2026-02-10"),
        ("FND-102", "PRJ-2026-001", "資安防護", "Medium", "生產環境資料庫端口對區網全員開放", "PostgreSQL 5432 埠未針對應用伺服器設定安全群組 IP 白名單。", "Remediated", "2026-01-22", "2026-02-28"),
        ("FND-103", "PRJ-2026-002", "隱私合規", "Critical", "訂單記錄未遮罩信用卡號與身分證字號", "應用程式應用層 Log 在 DEBUG 級別下輸出完整 PAN 與個資。", "Remediated", "2026-02-05", "2026-02-15"),
        ("FND-104", "PRJ-2026-002", "資安防護", "High", "前端結帳 API 缺少速率限制 (Rate Limiting)", "未防範自動化腳本撞庫或阻斷服務攻擊風險。", "Open", "2026-02-12", "2026-04-30"),
        ("FND-105", "PRJ-2026-003", "存取控制", "Low", "已離職員工帳號未於 24 小時內停用", "抽查 20 筆離職員工，其中 1 筆於第 3 天才完成停權。", "Remediated", "2026-03-08", "2026-03-15"),
        ("FND-106", "PRJ-2026-004", "資料備份", "Medium", "通話錄音異地備份缺少每季還原演練紀錄", "備份檔存在 Azure Blob，但近 6 個月無完整還原測試紀錄。", "Accepted_Risk", "2026-04-15", "2026-06-30"),
        ("FND-107", "PRJ-2026-005", "資安防護", "Critical", "Kubernetes 容器叢集運行 Root 權限且存在漏洞", "核心微服務容器使用 root 身分運行，且 base image 含有 CVE-2025-XXXX 重大漏洞。", "Open", "2026-05-10", "2026-06-30"),
        ("FND-108", "PRJ-2026-005", "存取控制", "High", "K8s Secrets 儲存明文密碼未整合 Vault", "資料庫連線密鑰以 Base64 明文存放於 ConfigMap/Secret。", "Verifying", "2026-05-15", "2026-07-15"),
        ("FND-109", "PRJ-2026-007", "營運流程", "High", "外部協力廠商 VPN 連線無專用跳板機 (Bastion)", "第三方廠商可直接連入內網網段存取原始碼資料夾。", "Open", "2026-08-20", "2026-09-30"),
    ]
    cursor.executemany(
        "INSERT INTO audit_findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        findings_data
    )

    # 寫入各部門合規指標 (Department Metrics)
    dept_data = [
        ("D01", "資訊科技處", "台北總部", 65, 88.5, 1, "2026-Q3"),
        ("D02", "電子商務部", "台北總部", 42, 74.0, 2, "2026-Q3"),
        ("D03", "財務會計處", "台北總部", 28, 96.2, 0, "2026-Q3"),
        ("D04", "客戶服務部", "台中分處", 55, 82.0, 0, "2026-Q3"),
        ("D05", "雲端維運部", "雲端中心", 24, 68.0, 3, "2026-Q3"),
        ("D06", "人力資源處", "台北總部", 18, 91.5, 0, "2026-Q3"),
        ("D07", "物流供應鏈處", "高雄分處", 48, 85.0, 0, "2026-Q3"),
    ]
    cursor.executemany(
        "INSERT INTO department_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
        dept_data
    )

    # 寫入改善處置追蹤 (Remediation Records)
    remediation_data = [
        ("REM-001", "FND-101", "已全面導入 Microsoft Entra ID 條件式存取與 FIDO2 安全金鑰。", "Grace Chen", "2026-02-08", 45000),
        ("REM-002", "FND-102", "已調整網路安全組 (NSG)，封鎖公有網段並限制僅 API Gateway 存取。", "David Wang", "2026-02-25", 0),
        ("REM-003", "FND-103", "升級日誌遮罩過濾器 (Log Masking Filter)，信用卡號一律轉為 ************1234。", "Grace Chen", "2026-02-14", 30000),
        ("REM-004", "FND-105", "導入人資 HR 離職自動觸發 webhook，立即鎖定 AD 帳號。", "Sarah Lin", "2026-03-12", 15000),
    ]
    cursor.executemany(
        "INSERT INTO remediation_records VALUES (?, ?, ?, ?, ?, ?)",
        remediation_data
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database(force_recreate=True)
    print(f"Successfully initialized audit database at: {DB_FILE}")
