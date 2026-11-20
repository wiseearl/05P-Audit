"""Cross-System Fraud Detection & Audit Anomaly Analyzer.

專門為內部稽核（Internal Audit）設計之全量跨系統交叉比對引擎：
1. 利益衝突與關係人舞弊 (HR 員工清冊 vs ERP 供應商主檔)
2. 採購拆單規避核決門檻 (採購單金額、時間窗口與廠商交叉比對)
3. 幽靈帳號與離職異常存取 (HR 離職紀錄 vs 核心系統/ERP/VPN 存取日誌)
4. 假發票與重複報銷偵測 (費用報銷單發票號碼與金額交叉比對)
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from db_init import DB_FILE


def _get_connection(db_path: Path = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# =====================================================================
# 規則 1：利益衝突與關係人舞弊 (Conflict of Interest)
# 比對 HR 員工清冊與 ERP 供應商主檔的銀行帳戶、電話、姓名
# =====================================================================

def detect_conflict_of_interest(db_path: Path = DB_FILE) -> list[dict[str, Any]]:
    """比對 HR 員工與 ERP 供應商之間的銀行帳戶、連絡電話或名稱是否重疊。"""
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    anomalies: list[dict[str, Any]] = []

    # 1. 銀行帳戶完全相同比對 (最高風險：資金可能直接回流至員工帳戶)
    cursor.execute("""
        SELECT 
            e.emp_id, e.emp_name, e.department, e.email, e.bank_account AS emp_bank, e.phone AS emp_phone,
            v.vendor_id, v.vendor_name, v.tax_id, v.contact_person, v.phone AS vendor_phone, v.bank_account AS vendor_bank
        FROM hr_employees e
        JOIN erp_vendors v ON e.bank_account = v.bank_account
        WHERE e.status != 'Deleted';
    """)
    rows = cursor.fetchall()

    for r in rows:
        # 查詢是否有對此供應商的採購記錄
        cursor.execute("""
            SELECT po_id, po_date, buyer_emp_id, amount_twd, item_description, status, approver
            FROM procurement_orders
            WHERE vendor_id = ?
            ORDER BY po_date DESC;
        """, (r["vendor_id"],))
        po_rows = [dict(po) for po in cursor.fetchall()]
        total_spent = sum(po["amount_twd"] for po in po_rows)

        anomalies.append({
            "finding_id": f"FRAUD-COI-BANK-{r['emp_id']}-{r['vendor_id']}",
            "rule_id": "RULE-COI-01",
            "category": "利益衝突與關係人交易",
            "severity": "CRITICAL",
            "title": "員工銀行帳戶與 ERP 供應商登記帳戶完全相符 (嚴重舞弊紅旗)",
            "employee": {
                "emp_id": r["emp_id"],
                "name": r["emp_name"],
                "department": r["department"],
                "bank_account": r["emp_bank"],
                "phone": r["emp_phone"]
            },
            "vendor": {
                "vendor_id": r["vendor_id"],
                "vendor_name": r["vendor_name"],
                "contact_person": r["contact_person"],
                "tax_id": r["tax_id"],
                "bank_account": r["vendor_bank"],
                "phone": r["vendor_phone"]
            },
            "match_fields": ["bank_account", "phone", "contact_person" if r["emp_name"] == r["contact_person"] else None],
            "related_orders_count": len(po_rows),
            "total_procurement_amount": total_spent,
            "orders": po_rows,
            "risk_impact": "資金可能由公司採購預算直接流入員工私人或關係企業銀行帳號，存在收受回扣、利益輸送或偽設人頭公司之重大舞弊嫌疑。",
            "audit_recommendation": "1. 立即暫停對該供應商所有款項撥付。\n2. 將事證移送人資考績會與法務/政風單位專案調查。\n3. 清查該員工過去經手之所有採購標案與報銷單據。"
        })

    # 2. 電話相同但帳戶不同 (潛在關係人關聯)
    cursor.execute("""
        SELECT 
            e.emp_id, e.emp_name, e.department, e.bank_account AS emp_bank, e.phone AS emp_phone,
            v.vendor_id, v.vendor_name, v.tax_id, v.contact_person, v.phone AS vendor_phone, v.bank_account AS vendor_bank
        FROM hr_employees e
        JOIN erp_vendors v ON e.phone = v.phone
        WHERE e.bank_account != v.bank_account;
    """)
    rows_phone = cursor.fetchall()
    for r in rows_phone:
        anomalies.append({
            "finding_id": f"FRAUD-COI-PHONE-{r['emp_id']}-{r['vendor_id']}",
            "rule_id": "RULE-COI-02",
            "category": "利益衝突與關係人交易",
            "severity": "HIGH",
            "title": "員工聯絡電話與供應商登記聯絡電話相符",
            "employee": {"emp_id": r["emp_id"], "name": r["emp_name"], "department": r["department"], "phone": r["emp_phone"]},
            "vendor": {"vendor_id": r["vendor_id"], "vendor_name": r["vendor_name"], "contact_person": r["contact_person"], "phone": r["vendor_phone"]},
            "match_fields": ["phone"],
            "risk_impact": "供應商登記之連絡電話為現職員工手機，可能為未揭露之關係人或人頭廠商。",
            "audit_recommendation": "要求該員工簽署「利益迴避與親屬關係揭露聲明書」，並由稽核處啟動實地訪查。"
        })

    conn.close()
    return anomalies


# =====================================================================
# 規則 2：採購拆單規避核決門檻 (Split Purchase Orders / Smurfing)
# 檢查同一部門或申請人、同一天或短期內向同一廠商開立多張逼近門檻的 PO
# =====================================================================

def detect_split_purchases(
    threshold_limit: float = 100000.0,
    window_days: int = 3,
    db_path: Path = DB_FILE
) -> list[dict[str, Any]]:
    """偵測是否有將高額採購拆單為多筆低於簽核門檻（如 10 萬元）的異常訂單。"""
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    anomalies: list[dict[str, Any]] = []

    # 找出同一天、同一採購人、同一供應商開立多筆訂單的群組
    cursor.execute("""
        SELECT 
            p.po_date, p.vendor_id, v.vendor_name, p.buyer_emp_id, e.emp_name, p.department,
            COUNT(p.po_id) AS po_count,
            SUM(p.amount_twd) AS total_amount,
            MAX(p.amount_twd) AS max_single_amount,
            MIN(p.amount_twd) AS min_single_amount
        FROM procurement_orders p
        JOIN erp_vendors v ON p.vendor_id = v.vendor_id
        JOIN hr_employees e ON p.buyer_emp_id = e.emp_id
        GROUP BY p.po_date, p.vendor_id, p.buyer_emp_id
        HAVING COUNT(p.po_id) > 1;
    """)
    candidate_groups = cursor.fetchall()

    for g in candidate_groups:
        total_amt = g["total_amount"]
        # 判斷條件：單筆未達門檻，但總和超過門檻，且至少一筆金額達到門檻的 70% 以上 (例如 7 萬 ~ 9.9 萬)
        if total_amt >= threshold_limit and g["max_single_amount"] < threshold_limit:
            # 撈取這些訂單明細
            cursor.execute("""
                SELECT po_id, po_date, amount_twd, item_description, status, approver
                FROM procurement_orders
                WHERE po_date = ? AND vendor_id = ? AND buyer_emp_id = ?
                ORDER BY po_id;
            """, (g["po_date"], g["vendor_id"], g["buyer_emp_id"]))
            orders = [dict(row) for row in cursor.fetchall()]

            anomalies.append({
                "finding_id": f"FRAUD-SPLIT-{g['po_date']}-{g['vendor_id']}",
                "rule_id": "RULE-PO-SPLIT-01",
                "category": "採購循環與核決合規",
                "severity": "HIGH",
                "title": f"採購訂單疑似蓄意化整為零拆單 (規避核決門檻 NT$ {int(threshold_limit):,})",
                "summary": (
                    f"採購人 {g['emp_name']} ({g['buyer_emp_id']}) 於 {g['po_date']} 向廠商「{g['vendor_name']}」"
                    f"連續開立 {g['po_count']} 筆訂單，單筆金額皆低於 {int(threshold_limit):,}，"
                    f"但當日累計金額高達 NT$ {int(total_amt):,}，且品項高度關聯。"
                ),
                "date": g["po_date"],
                "buyer": {"emp_id": g["buyer_emp_id"], "name": g["emp_name"], "department": g["department"]},
                "vendor": {"vendor_id": g["vendor_id"], "vendor_name": g["vendor_name"]},
                "threshold_limit": threshold_limit,
                "total_split_amount": total_amt,
                "split_orders": orders,
                "risk_impact": "規避《採購核決權限辦法》規定之處長/總經理層級簽核與公開比議價程序，可能涉及私相授受或圖利特定廠商。",
                "audit_recommendation": "1. 訪談承辦人與核決主管，查明同日拆單之業務合理性。\n2. 複查該批設備合約完整規格，確認是否為不可分割之單一專案。\n3. 系統端應增設「同日同廠商累計金額」自動阻斷或升級核決流程。"
            })

    conn.close()
    return anomalies


# =====================================================================
# 規則 3：幽靈帳號與離職異常存取 (Zombie Accounts & Leaver Access)
# 比對 HR 離職員工清冊與系統日誌 (Terminated Employee vs System Logs)
# =====================================================================

def detect_zombie_accounts(db_path: Path = DB_FILE) -> list[dict[str, Any]]:
    """比對已離職員工在離職生效日之後，仍有系統登入或資料匯出之重大異常紀錄。"""
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    anomalies: list[dict[str, Any]] = []

    cursor.execute("""
        SELECT 
            l.log_id, l.access_time, l.emp_id, l.action_type, l.source_ip, l.system_name, l.result,
            e.emp_name, e.department, e.email, e.status AS hr_status, e.term_date
        FROM system_access_logs l
        JOIN hr_employees e ON l.emp_id = e.emp_id
        WHERE e.status = 'Terminated' 
          AND e.term_date IS NOT NULL
          AND DATE(l.access_time) > DATE(e.term_date)
        ORDER BY l.access_time DESC;
    """)
    rows = cursor.fetchall()

    # 依員工彙整異常日誌
    grouped: dict[str, list[dict[str, Any]]] = {}
    emp_meta: dict[str, dict[str, Any]] = {}

    for r in rows:
        eid = r["emp_id"]
        if eid not in grouped:
            grouped[eid] = []
            emp_meta[eid] = {
                "emp_id": eid,
                "name": r["emp_name"],
                "department": r["department"],
                "email": r["email"],
                "term_date": r["term_date"]
            }
        grouped[eid].append({
            "log_id": r["log_id"],
            "access_time": r["access_time"],
            "action_type": r["action_type"],
            "system_name": r["system_name"],
            "source_ip": r["source_ip"],
            "result": r["result"]
        })

    for eid, logs in grouped.items():
        meta = emp_meta[eid]
        # 判斷嚴重度：若有 Export_Data 或外網 IP 則為 CRITICAL，否則為 HIGH
        has_export = any(l["action_type"] == "Export_Data" for l in logs)
        has_external_ip = any(not l["source_ip"].startswith("192.168.") and not l["source_ip"].startswith("10.") for l in logs)

        severity = "CRITICAL" if (has_export or has_external_ip) else "HIGH"

        anomalies.append({
            "finding_id": f"FRAUD-ZOMBIE-{eid}",
            "rule_id": "RULE-ACCESS-ZOMBIE-01",
            "category": "身分識別與存取控制",
            "severity": severity,
            "title": "已離職員工帳號於離職日後仍有系統活動 (幽靈帳號存取)",
            "summary": (
                f"員工 {meta['name']} ({eid}, 前 {meta['department']}) 已於 {meta['term_date']} 正式離職生效，"
                f"但於離職後仍有 {len(logs)} 次系統活動記錄，"
                f"涉及系統：{', '.join(set(l['system_name'] for l in logs))}。"
                + (" 偵測到敏感資料匯出 (Export_Data) 及外部未知 IP 存取！" if has_export else "")
            ),
            "employee": meta,
            "incident_count": len(logs),
            "has_data_export": has_export,
            "has_external_ip": has_external_ip,
            "access_logs": logs,
            "risk_impact": "離職員工未即時註銷權限，可自外部連線竊取公司營業秘密、客戶個資或篡改財務總帳資料，違反 ISO 27001 與內控準則。",
            "audit_recommendation": "1. 立即於 AD/IdP 強制停用該帳號並撤銷所有 active tokens。\n2. 封鎖存取來源 IP 並通知資安事件應變小組 (CSIRT) 採證分析匯出資料內容。\n3. 檢討人資處與資訊處之離職帳號自動下線 Webhook 同步機制失敗原因。"
        })

    conn.close()
    return anomalies


# =====================================================================
# 規則 4：假發票與重複報銷 (Duplicate Invoices & Claims)
# 檢查費用報銷單中同一發票號碼被多次報銷的情況
# =====================================================================

def detect_duplicate_invoices(db_path: Path = DB_FILE) -> list[dict[str, Any]]:
    """比對費用報銷主檔，偵測同一發票號碼被多名員工重複請款之舞弊情事。"""
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    anomalies: list[dict[str, Any]] = []

    cursor.execute("""
        SELECT invoice_no, COUNT(*) AS claim_count, SUM(amount_twd) AS total_claimed
        FROM expense_claims
        GROUP BY invoice_no
        HAVING COUNT(*) > 1;
    """)
    dup_invoices = cursor.fetchall()

    for d in dup_invoices:
        inv_no = d["invoice_no"]
        cursor.execute("""
            SELECT 
                c.claim_id, c.claim_date, c.emp_id, e.emp_name, e.department, 
                c.amount_twd, c.purpose, c.status
            FROM expense_claims c
            JOIN hr_employees e ON c.emp_id = e.emp_id
            WHERE c.invoice_no = ?
            ORDER BY c.claim_date;
        """, (inv_no,))
        claims = [dict(c) for c in cursor.fetchall()]

        # 檢查是否為不同員工
        claim_employees = list(set(c["emp_name"] for c in claims))

        anomalies.append({
            "finding_id": f"FRAUD-DUP-INV-{inv_no}",
            "rule_id": "RULE-CLAIM-DUP-01",
            "category": "費用報銷與財務舞弊",
            "severity": "HIGH",
            "title": f"統一發票號碼重複報銷 (發票號: {inv_no})",
            "summary": (
                f"發票號碼「{inv_no}」被重複請款 {len(claims)} 次，累計請款金額 NT$ {int(d['total_claimed']):,}。"
                f" 請款人包含：{', '.join(claim_employees)}。"
            ),
            "invoice_no": inv_no,
            "claim_count": len(claims),
            "total_claimed_twd": d["total_claimed"],
            "claims": claims,
            "risk_impact": "涉及一單多報、虛偽請款或重複向公司支領經費，違反會計法規並損害公司資產。",
            "audit_recommendation": "1. 凍結該筆爭議款項並對重複請款同仁進行個別訪查與比對原始憑證正本。\n2. ERP 報銷系統前端應增加發票號碼唯一性檢核 (Unique Constraint) 與財政部電子發票載具即時驗證。"
        })

    conn.close()
    return anomalies


# =====================================================================
# 全量偵測綜合執行器 (Main Orchestrator)
# =====================================================================

def run_cross_system_fraud_audit(
    rule_filter: str = "all",
    db_path: Path = DB_FILE
) -> dict[str, Any]:
    """執行全量跨系統交叉比對與舞弊偵測，整合多個業務維度並產出稽核報告。

    Args:
        rule_filter: 執行規則過濾，支援 'all', 'conflict_of_interest', 'split_po',
                     'zombie_account', 'duplicate_invoice'。
        db_path: 資料庫檔案路徑。
    """
    rule_filter = (rule_filter or "all").lower().strip()
    findings: list[dict[str, Any]] = []

    rule_meta = [
        {"id": "RULE-COI", "name": "利益衝突與關係人舞弊比對", "scope": "HR 員工 vs ERP 供應商 (帳戶/電話/代表人)"},
        {"id": "RULE-SPLIT", "name": "採購拆單規避核決門檻比對", "scope": "採購單金額、時間窗口與廠商交叉分析"},
        {"id": "RULE-ZOMBIE", "name": "幽靈帳號與離職異常存取比對", "scope": "HR 離職生效日 vs ERP/核心資料庫/VPN 存取日誌"},
        {"id": "RULE-DUP-INV", "name": "假發票與重複報銷比對", "scope": "費用報銷單發票號碼跨員工重複核銷檢驗"},
    ]

    # 1. 利益衝突比對
    if rule_filter in ("all", "conflict_of_interest", "coi"):
        coi_findings = detect_conflict_of_interest(db_path)
        findings.extend(coi_findings)

    # 2. 採購拆單比對
    if rule_filter in ("all", "split_po", "split_purchases", "split"):
        split_findings = detect_split_purchases(db_path=db_path)
        findings.extend(split_findings)

    # 3. 幽靈帳號存取比對
    if rule_filter in ("all", "zombie_account", "zombie"):
        zombie_findings = detect_zombie_accounts(db_path)
        findings.extend(zombie_findings)

    # 4. 重複報銷比對
    if rule_filter in ("all", "duplicate_invoice", "dup_invoice"):
        dup_findings = detect_duplicate_invoices(db_path)
        findings.extend(dup_findings)

    # 統計重大度
    critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
    high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
    medium_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    low_count = sum(1 for f in findings if f.get("severity") == "LOW")

    overall_risk = "CRITICAL" if critical_count > 0 else ("HIGH" if high_count > 0 else "MEDIUM" if findings else "LOW")

    # 1. 產生正宗圓形圓餅圖 QuickChart 圖片連結 (相容於 Antigravity，避免 Mermaid pie 報錯)
    pie_labels = []
    pie_data = []
    pie_colors = []
    if critical_count > 0:
        pie_labels.append(f"Critical 重大 ({critical_count})")
        pie_data.append(critical_count)
        pie_colors.append("#d32f2f")
    if high_count > 0:
        pie_labels.append(f"High 高風險 ({high_count})")
        pie_data.append(high_count)
        pie_colors.append("#f57c00")
    if medium_count > 0:
        pie_labels.append(f"Medium 中風險 ({medium_count})")
        pie_data.append(medium_count)
        pie_colors.append("#fbc02d")
    if low_count > 0:
        pie_labels.append(f"Low 低風險 ({low_count})")
        pie_data.append(low_count)
        pie_colors.append("#388e3c")

    qc_config = {
        "type": "pie",
        "data": {
            "labels": pie_labels,
            "datasets": [{
                "data": pie_data,
                "backgroundColor": pie_colors
            }]
        },
        "options": {
            "plugins": {
                "legend": {"position": "right"}
            }
        }
    }
    encoded_cfg = urllib.parse.quote(json.dumps(qc_config))
    image_markdown = f"![跨系統舞弊紅旗嚴重度分佈](https://quickchart.io/chart?c={encoded_cfg}&w=480&h=240)"

    # 2. 產生相容於 Antigravity 的 xychart-beta 長條圖
    max_count = max(critical_count, high_count, medium_count, low_count, 1)
    xychart_mermaid = (
        f"xychart-beta\n"
        f'    title "跨系統舞弊紅旗嚴重度分佈"\n'
        f'    x-axis ["CRITICAL", "HIGH", "MEDIUM", "LOW"]\n'
        f'    y-axis "異常筆數" 0 --> {max_count + 2}\n'
        f'    bar [{critical_count}, {high_count}, {medium_count}, {low_count}]'
    )

    # 3. 產生相容於 Antigravity 的 flowchart LR 流程結構圖
    flowchart_mermaid = (
        f"flowchart LR\n"
        f'    Root["🚨 跨系統舞弊偵測 (共 {len(findings)} 筆)"]\n'
        f'    Root --> C["CRITICAL: {critical_count} 筆"]\n'
        f'    Root --> H["HIGH: {high_count} 筆"]\n'
        f'    style C fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c\n'
        f'    style H fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#e65100'
    )

    # 組裝 Markdown 摘要供 LLM 與審計員直接閱讀
    report_lines = [
        "# 全量跨系統交叉比對與舞弊偵測報告 (Cross-System Fraud Audit Report)",
        f"- 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 稽核範疇: HR 員工系統、ERP 供應商主檔、採購審批記錄、身分認證/存取日誌、費用報銷系統",
        f"- 檢測規則: {len(rule_meta)} 項核心舞弊指標",
        f"- 整體風險判定: **{overall_risk}**",
        f"- 發現異常缺失數: **{len(findings)} 筆** (Critical: {critical_count}, High: {high_count}, Medium: {medium_count})",
        "",
        "## 舞弊紅旗嚴重度視覺化分佈",
        image_markdown,
        "",
        "---",
        "## 異常事件彙整清單",
    ]

    for idx, f in enumerate(findings, 1):
        report_lines.append(f"### {idx}. [{f['severity']}] {f['title']}")
        report_lines.append(f"- **缺失編號**: `{f['finding_id']}` ({f['category']})")
        if "summary" in f:
            report_lines.append(f"- **事證摘要**: {f['summary']}")
        elif "risk_impact" in f:
            report_lines.append(f"- **風險影響**: {f['risk_impact']}")
        report_lines.append(f"- **審計改善建議**:\n{f.get('audit_recommendation', '無')}")
        report_lines.append("")

    return {
        "status": "completed",
        "audit_timestamp": datetime.now().isoformat(),
        "overall_risk_level": overall_risk,
        "rule_filter_applied": rule_filter,
        "total_anomalies_detected": len(findings),
        "severity_summary": {
            "CRITICAL": critical_count,
            "HIGH": high_count,
            "MEDIUM": medium_count,
            "LOW": low_count,
        },
        "visual_charts": {
            "rendering_restriction": (
                "CRITICAL WARNING: Antigravity UI does NOT support ```mermaid pie (will crash with 'Invalid mermaid header'). "
                "DO NOT generate ```mermaid pie! Use the provided image_markdown (QuickChart pie chart) or xychart_mermaid instead."
            ),
            "image_markdown": image_markdown,
            "xychart_mermaid": xychart_mermaid,
            "flowchart_mermaid": flowchart_mermaid,
        },
        "findings": findings,
        "markdown_report": "\n".join(report_lines)
    }


if __name__ == "__main__":
    print("Testing Fraud Detector...")
    res = run_cross_system_fraud_audit("all")
    print(f"Total findings: {res['total_anomalies_detected']}")
    for f in res["findings"]:
        print(f"[{f['severity']}] {f['finding_id']} - {f['title']}")
