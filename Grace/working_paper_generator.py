"""Audit Working Paper & Report Generator Module (Markdown & Word).

專為審計部設計的標準「內部稽核工作底稿 (Audit Working Paper)」與正式報告生成器。
支援一鍵輸出 Markdown 格式 (.md) 與 Microsoft Word 格式 (.docx)。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from db_init import DB_FILE

OUTPUT_DIR = Path(__file__).resolve().parent / "generated_working_papers"


def _get_project_data(project_id: str) -> dict[str, Any] | None:
    """從資料庫讀取專案完整中繼資料、缺失清單與改善處置。"""
    if not DB_FILE.exists():
        return None

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 查詢專案資訊
    cursor.execute("SELECT * FROM audit_projects WHERE id = ?;", (project_id,))
    proj_row = cursor.fetchone()
    if not proj_row:
        conn.close()
        return None
    project = dict(proj_row)

    # 2. 查詢該專案的缺失
    cursor.execute("SELECT * FROM audit_findings WHERE project_id = ? ORDER BY severity ASC;", (project_id,))
    findings = [dict(r) for r in cursor.fetchall()]

    # 3. 查詢相關改善紀錄
    finding_ids = [f["id"] for f in findings]
    remediations = {}
    if finding_ids:
        placeholders = ",".join("?" * len(finding_ids))
        cursor.execute(f"SELECT * FROM remediation_records WHERE finding_id IN ({placeholders});", finding_ids)
        for r in cursor.fetchall():
            remediations[r["finding_id"]] = dict(r)

    conn.close()

    return {
        "project": project,
        "findings": findings,
        "remediations": remediations,
    }


def generate_markdown_working_paper(data: dict[str, Any], output_path: Path) -> str:
    """生成標準審計工作底稿 Markdown 格式。"""
    project = data["project"]
    findings = data["findings"]
    remediations = data["remediations"]

    wp_code = f"WP-{project['id']}"
    now_str = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# 【內部稽核工作底稿】Audit Working Paper",
        f"**底稿編號**：`{wp_code}` ｜ **建立日期**：`{now_str}` ｜ **機密等級**：內部限閱 (Confidential)",
        "",
        "---",
        "",
        "## 壹、 查核基本資料 (Audit Metadata)",
        "",
        "| 項目 | 查核登錄內容 |",
        "| :--- | :--- |",
        f"| **專案名稱** | {project['project_name']} |",
        f"| **受稽核單位** | {project['department']} |",
        f"| **專案代碼** | {project['id']} |",
        f"| **主查稽核員** | {project['lead_auditor']} |",
        f"| **複核主管** | 審計部主任稽核 / 總稽核 |",
        f"| **查核區間** | {project['start_date']} 至 {project['end_date'] or '進行中'} |",
        f"| **綜合風險評估** | **{project['overall_risk']}** |",
        f"| **合規綜合評分** | **{project['score']} / 100 分** |",
        f"| **專案審計狀態** | `{project['status']}` |",
        "",
        "---",
        "",
        "## 貳、 查核目的與查核範圍 (Audit Objectives & Scope)",
        "",
        f"1. **查核目的**：評估「{project['department']}」於執行業務及維運核心系統期間，是否落實內部控制制度規範、資安合規指引與法定責任。",
        f"2. **查核範圍**：涵蓋受查期間內之架構設定、系統連線通道、權限劃分、交易記錄及相關留存軌跡。",
        "3. **抽樣方法**：採全量自動化規章檢查與高風險模組重點查核（Non-statistical Judgmental Sampling & Automated Census）。",
        "",
        "---",
        "",
        "## 參、 查核程序與測試方法 (Audit Procedures & Testing Methods)",
        "",
        "1. 透過稽核專用唯讀探針與安全 SQL 查詢提取受查系統組態及關鍵資料表記錄。",
        "2. 比對企業《內部控制制度》、《資訊安全作業準則》及相關法定規範。",
        "3. 驗證資料遮罩、特權帳號管理（MFA/Vault）及存取安全策略實施現況。",
        "",
        "---",
        "",
        "## 肆、 查核發現與佐證清單 (Audit Findings & Evidence)",
        "",
    ]

    if not findings:
        lines.append("> 查核期間未發現重大內部控制缺失或異常項目。\n")
    else:
        lines.append(f"本專案共查得 **{len(findings)} 項** 缺失事實，彙總如下：\n")
        lines.append("| 缺失編號 | 嚴重等級 | 缺失主旨 | 類別 | 狀態 | 改善期限 |")
        lines.append("| :---: | :---: | :--- | :---: | :---: | :---: |")
        for f in findings:
            sev_badge = f"**{f['severity']}**"
            lines.append(f"| `{f['id']}` | {sev_badge} | {f['title']} | {f['category']} | `{f['status']}` | {f['remediation_due']} |")
        lines.append("")

        lines.append("### 4.1 缺失詳細事實陳述與內控法規依據\n")
        for idx, f in enumerate(findings, 1):
            rem = remediations.get(f["id"])
            rem_str = rem["action_taken"] if rem else "受稽單位尚未提出具體改善行動或尚在評估中。"
            lines.extend([
                f"#### [{idx}] 缺失項目：{f['title']} (`{f['id']}`)",
                f"- **風險嚴重等級**：`{f['severity']}` ｜ **缺失分類**：`{f['category']}`",
                f"- **查核事實 (Observation)**：{f['description']}",
                f"- **內控與法規依據 (Criteria)**：依據本公司《內部控制制度管理辦法》及《資訊系統安全規範》相關款項，受查系統應維持存取隔離與最小授權原則。",
                f"- **潛在風險與衝擊 (Risk & Impact)**：可能導致機敏系統遭受未授權存取、橫向移動滲透或個資資料洩漏。",
                f"- **改善處置措施 (Management Action Plan)**：{rem_str}",
                f"- **複查改善期限**：`{f['remediation_due']}`",
                "",
            ])

    lines.extend([
        "---",
        "",
        "## 伍、 稽核結論與綜合改善建議 (Audit Conclusion & Recommendations)",
        "",
        f"本次查核針對「{project['department']}」實施查核，綜合評分為 **{project['score']} 分**（風險等級：**{project['overall_risk']}**）。",
        "1. **短期應變措施**：受稽單位應針對 Critical / High 等級缺失立即採取緩解防護，並於指定到期日前向審計部提交佐證記錄。",
        "2. **長期體質改善**：建請受稽單位主管將自動化合規監控整合至日常作業，健全第一道防線之自主控管機制。",
        "",
        "---",
        "",
        "## 陸、 審計簽核與覆核記錄 (Sign-off & Approvals)",
        "",
        "| 角色 | 簽核人員 | 簽核意見 | 簽署日期 |",
        "| :--- | :--- | :--- | :--- |",
        f"| **主查稽核員** | {project['lead_auditor']} | 查核事實明確，底稿佐證資料齊全，送請覆核。 | {now_str} |",
        "| **複核督導** | 審計主管 | 查核程序妥適，同意缺失認定與改善建議，陳報委員會。 | 待核 |",
        "",
    ])

    content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return content


def generate_docx_working_paper(data: dict[str, Any], output_path: Path) -> None:
    """生成標準審計工作底稿 Microsoft Word (.docx) 格式。"""
    try:
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.oxml import parse_xml, OxmlElement
        from docx.oxml.ns import nsdecls, qn
    except ImportError:
        raise RuntimeError("系統未安裝 python-docx 套件，請執行 pip install python-docx")

    project = data["project"]
    findings = data["findings"]
    remediations = data["remediations"]
    wp_code = f"WP-{project['id']}"
    now_str = datetime.now().strftime("%Y-%m-%d")

    doc = docx.Document()

    # 設定邊界
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    # 1. 主標題
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    title_run = title_p.add_run("內部稽核工作底稿 (Audit Working Paper)")
    title_run.font.size = Pt(20)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A) # 專業深藍

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_after = Pt(16)
    sub_run = sub_p.add_run(f"底稿編號：{wp_code}  ｜  建立日期：{now_str}  ｜  機密等級：內部限閱 (Confidential)")
    sub_run.font.size = Pt(10)
    sub_run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

    # 2. 基本資料表 (Metadata Table)
    doc.add_heading("壹、 查核基本資料", level=2)
    meta_table = doc.add_table(rows=5, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.style = "Table Grid"

    meta_rows = [
        [("專案名稱", True), (project["project_name"], False), ("受稽核單位", True), (project["department"], False)],
        [("專案代碼", True), (project["id"], False), ("主查稽核員", True), (project["lead_auditor"], False)],
        [("查核區間", True), (f"{project['start_date']} ~ {project['end_date'] or '進行中'}", False), ("綜合評分", True), (f"{project['score']} / 100 分", False)],
        [("綜合風險評級", True), (project["overall_risk"], False), ("目前狀態", True), (project["status"], False)],
        [("複核主管", True), ("審計部主任稽核 / 總稽核", False), ("法定標準", True), ("內控準則 / ISO 27001", False)],
    ]

    for row_idx, row_content in enumerate(meta_rows):
        row_cells = meta_table.rows[row_idx].cells
        for col_idx, (text, is_header) in enumerate(row_content):
            cell = row_cells[col_idx]
            cell.text = text
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            if is_header:
                p.runs[0].font.bold = True
                p.runs[0].font.size = Pt(9.5)
                # 淺灰藍背景
                shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F1F5F9"/>')
                cell._tc.get_or_add_tcPr().append(shading)
            else:
                p.runs[0].font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # 3. 查核目的與範圍
    doc.add_heading("貳、 查核目的、範圍與測試方法", level=2)
    p_obj = doc.add_paragraph()
    p_obj.paragraph_format.space_after = Pt(4)
    p_obj.add_run(f"1. 查核目的：評估「{project['department']}」於執行業務期間，是否落實內部控制制度規範與資安合規管理。\n"
                  f"2. 查核範圍：涵蓋系統設定檔、雲端叢集通道、特權存取記錄與交易日誌。\n"
                  f"3. 測試方法：透過 Grace MCP 安全唯讀查庫及日誌探針實施全量比對檢驗。")

    # 4. 缺失彙總表
    doc.add_heading(f"參、 查核發現與佐證清單 (共 {len(findings)} 筆)", level=2)
    if not findings:
        doc.add_paragraph("查核期間未發現顯著內控缺失。")
    else:
        table = doc.add_table(rows=len(findings) + 1, cols=6)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

        headers = ["缺失編號", "風險等級", "缺失主旨", "缺失類別", "狀態", "改善期限"]
        hdr_cells = table.rows[0].cells
        for idx, h_text in enumerate(headers):
            hdr_cells[idx].text = h_text
            p = hdr_cells[idx].paragraphs[0]
            p.runs[0].font.bold = True
            p.runs[0].font.size = Pt(9.5)
            p.runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="1E3A8A"/>')
            hdr_cells[idx]._tc.get_or_add_tcPr().append(shading)

        for row_idx, f in enumerate(findings, 1):
            row_cells = table.rows[row_idx].cells
            vals = [f["id"], f["severity"], f["title"], f["category"], f["status"], f["remediation_due"]]
            for col_idx, val in enumerate(vals):
                row_cells[col_idx].text = str(val)
                p = row_cells[col_idx].paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                p.runs[0].font.size = Pt(9)
                # 風險等級標色
                if col_idx == 1:
                    p.runs[0].font.bold = True
                    sev = str(val).lower()
                    if "critical" in sev:
                        p.runs[0].font.color.rgb = RGBColor(0xD3, 0x2F, 0x2F)
                    elif "high" in sev:
                        p.runs[0].font.color.rgb = RGBColor(0xF5, 0x7C, 0x00)
                    elif "medium" in sev:
                        p.runs[0].font.color.rgb = RGBColor(0xD9, 0x77, 0x06)

    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # 5. 缺失細部論述
    doc.add_heading("肆、 缺失細部事實陳述與改善方案", level=2)
    for idx, f in enumerate(findings, 1):
        rem = remediations.get(f["id"])
        rem_str = rem["action_taken"] if rem else "受稽單位尚在研擬處置方案中。"

        p_find = doc.add_paragraph()
        p_find.paragraph_format.space_before = Pt(6)
        p_find.paragraph_format.space_after = Pt(2)
        r_head = p_find.add_run(f"【缺失 {idx}】{f['title']} (編號: {f['id']})")
        r_head.font.bold = True
        r_head.font.size = Pt(11)

        p_desc = doc.add_paragraph()
        p_desc.paragraph_format.space_after = Pt(2)
        p_desc.add_run(f"• 嚴重等級：{f['severity']}   |   缺失分類：{f['category']}\n"
                       f"• 查核事實 (Observation)：{f['description']}\n"
                       f"• 內控法規依據 (Criteria)：違背本公司《內部控制作業規章》及存取隔離原則。\n"
                       f"• 改善處置建議 (Remediation)：{rem_str}\n"
                       f"• 改善完成期限：{f['remediation_due']}")

    # 6. 結論與簽核
    doc.add_heading("伍、 稽核結論與簽核記錄", level=2)
    p_concl = doc.add_paragraph()
    p_concl.add_run(f"受查單位綜合評分為 {project['score']} 分，綜合風險等級為 {project['overall_risk']}。\n"
                    f"建請受查單位主管責成權責同仁於限期內完成改善佐證提交。")

    sign_table = doc.add_table(rows=3, cols=3)
    sign_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    sign_table.style = "Table Grid"
    sign_headers = ["簽核角色", "簽名 / 職銜", "簽署日期"]
    for i, h in enumerate(sign_headers):
        sign_table.rows[0].cells[i].text = h
        sign_table.rows[0].cells[i].paragraphs[0].runs[0].font.bold = True

    sign_table.rows[1].cells[0].text = "主查稽核員"
    sign_table.rows[1].cells[1].text = f"{project['lead_auditor']} (簽名)"
    sign_table.rows[1].cells[2].text = now_str

    sign_table.rows[2].cells[0].text = "審計主管覆核"
    sign_table.rows[2].cells[1].text = "總稽核 / 主任稽核 (覆核意見：同意)"
    sign_table.rows[2].cells[2].text = "待核"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))


def generate_working_paper(project_id: str, output_format: str = "both") -> dict[str, Any]:
    """一鍵產出審計工作底稿。

    Args:
        project_id: 專案代碼（如 PRJ-2026-005, PRJ-2026-001）。
        output_format: 匯出格式，支援 'markdown', 'docx', 或 'both' (同時產生兩者)。
    """
    data = _get_project_data(project_id)
    if not data:
        return {"success": False, "error": f"找不到專案代碼 '{project_id}'"}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fmt = output_format.lower().strip()

    generated_files = []
    preview_snippet = ""

    # 生成 Markdown
    if fmt in ("markdown", "both"):
        md_file = OUTPUT_DIR / f"WP_{project_id}.md"
        content = generate_markdown_working_paper(data, md_file)
        generated_files.append({"format": "markdown", "path": str(md_file.resolve())})
        preview_snippet = content[:600] + "..."

    # 生成 Word (.docx)
    if fmt in ("docx", "both"):
        docx_file = OUTPUT_DIR / f"WP_{project_id}.docx"
        try:
            generate_docx_working_paper(data, docx_file)
            generated_files.append({"format": "docx", "path": str(docx_file.resolve())})
        except Exception as e:
            return {"success": False, "error": f"Word 格式底稿生成失敗: {e}"}

    project = data["project"]
    return {
        "success": True,
        "project_id": project_id,
        "project_name": project["project_name"],
        "department": project["department"],
        "findings_count": len(data["findings"]),
        "generated_files": generated_files,
        "preview_snippet": preview_snippet,
        "message": f"已成功產出專案 '{project_id}' 之標準審計工作底稿（含 Markdown 與 Word 格式）！",
    }


if __name__ == "__main__":
    res = generate_working_paper("PRJ-2026-005", output_format="both")
    print(res)
