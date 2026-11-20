"""Audit Analytics & Database Insights MCP Server (MCP v2 Streamable HTTP).

專門為稽核（Audit）、合規分析與資料庫視覺化設計的 MCP 伺服器。
提供安全唯讀 SQL 查詢、Schema 探測、資料統計 Profile，以及自動生成 Mermaid 視覺化圖表語法。
預設監聽 0.0.0.0:8001/mcp，支援本地與虛擬機（VM）跨機連線。
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import sqlite3
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from db_init import DB_FILE, init_database
import api_tester
import working_paper_generator
import fraud_detector

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8001"))

# 確保資料庫存在並已有種子資料
init_database()

mcp = MCPServer(
    name="grace-audit-suite-mcp",
    instructions=(
        "這是一個企業級稽核數據分析（Audit Analytics）、API 契約品質檢驗、"
        "審計工作底稿自動生成（Working Paper Generator）與跨系統舞弊偵測（Fraud Detection）的 MCP 伺服器。"
        "提供安全唯讀 SQL 查詢、資料剖析、Mermaid/SVG 視覺化圖表生成、"
        "OpenAPI 規格解析、智慧 mock 測資生成、一鍵產出標準審計工作底稿（Markdown 與 Word docx 格式），"
        "以及跨系統資料比對（HR vs ERP 關係人、採購拆單、離職幽靈帳號、重複報銷）。\n\n"
        "【前端圖表渲染限制】：Antigravity 介面不支援 Mermaid 'pie' 語法（輸出 ```mermaid pie 會導致 Invalid mermaid header 錯誤崩潰）。"
        "若需視覺化圓餅圖或分佈，請一律使用工具回傳之 image_markdown（QuickChart 圖片）或使用 xychart-beta 長條圖 / flowchart LR 呈現，嚴禁輸出 ```mermaid pie 語法。"
    ),
)


def _get_lan_ip() -> str:
    """自動偵測本機或 VM 在區網中的 IPv4 位址。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def _get_connection() -> sqlite3.Connection:
    """取得 SQLite 唯讀或一般連線。"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# 限制僅能執行唯讀查詢的正規表示式
DISALLOWED_SQL_PATTERNS = [
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|TRUNCATE|VACUUM)\b",
    r"\bPRAGMA\s+(?!table_info)",  # 只允許 PRAGMA table_info，其餘 PRAGMA 禁止
]


# =====================================================================
# 1. 資料庫結構與總覽工具
# =====================================================================

@mcp.tool()
def get_db_overview() -> dict[str, Any]:
    """取得稽核資料庫的基本資訊、資料表清單以及各表總筆數。"""
    if not DB_FILE.exists():
        init_database()

    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row["name"] for row in cursor.fetchall()]

    table_stats = []
    total_records = 0
    for tbl in tables:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {tbl};")  # noqa: S608
        cnt = cursor.fetchone()["cnt"]
        total_records += cnt
        table_stats.append({"table_name": tbl, "row_count": cnt})

    conn.close()

    return {
        "db_name": DB_FILE.name,
        "db_size_kb": round(DB_FILE.stat().st_size / 1024, 2),
        "total_tables": len(tables),
        "total_records": total_records,
        "tables": table_stats,
        "endpoint": f"http://{_get_lan_ip()}:{PORT}/mcp",
    }


@mcp.tool()
def get_table_schema(table_name: str = "") -> dict[str, Any]:
    """查詢資料庫資料表結構（欄位名稱、資料型態、主鍵與預設值）。

    Args:
        table_name: 指定資料表名稱（如 audit_projects, audit_findings, department_metrics, remediation_records）。若留空則回傳全部資料表結構。
    """
    conn = _get_connection()
    cursor = conn.cursor()

    if table_name:
        cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name = ?;",
            (table_name,),
        )
    else:
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")

    rows = cursor.fetchall()
    if not rows and table_name:
        conn.close()
        return {"success": False, "error": f"找不到資料表 '{table_name}'"}

    result = {}
    for r in rows:
        tbl = r["name"]
        create_sql = r["sql"]

        # 取得欄位詳細定義
        cursor.execute(f"PRAGMA table_info({tbl});")
        columns = [
            {
                "cid": col["cid"],
                "name": col["name"],
                "type": col["type"],
                "notnull": bool(col["notnull"]),
                "dflt_value": col["dflt_value"],
                "pk": bool(col["pk"]),
            }
            for col in cursor.fetchall()
        ]
        result[tbl] = {
            "columns": columns,
            "ddl": create_sql,
        }

    conn.close()
    return {"success": True, "schemas": result}


# =====================================================================
# 2. 安全 SQL 查詢與資料剖析工具
# =====================================================================

@mcp.tool()
def safe_sql_query(query: str, max_rows: int = 100) -> dict[str, Any]:
    """執行安全唯讀的 SQL 查詢（僅允許 SELECT 語句）。

    Args:
        query: 要執行的 SQL 查詢語句（例如：SELECT department, AVG(score) FROM audit_projects GROUP BY department）。
        max_rows: 最多回傳幾筆資料（預設 100 筆，上限 500 筆）。
    """
    clean_query = query.strip()
    upper_query = clean_query.upper()

    # 安全檢查：阻擋修改型語句
    for pattern in DISALLOWED_SQL_PATTERNS:
        if re.search(pattern, upper_query, re.IGNORECASE):
            return {
                "success": False,
                "error": "安全限制違規：此 MCP 工具僅支援唯讀 (SELECT) 查詢，禁止執行資料變更或結構異動語句。",
            }

    # 必須以 SELECT 或 WITH 開頭
    if not (upper_query.startswith("SELECT") or upper_query.startswith("WITH")):
        return {
            "success": False,
            "error": "無效的查詢：語句必須以 SELECT 或 WITH (CTE) 開頭。",
        }

    max_rows = max(1, min(max_rows, 500))

    start_time = time.perf_counter()
    conn = _get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(clean_query)
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []
        fetched_rows = cursor.fetchmany(max_rows)
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        data = [dict(zip(col_names, row)) for row in fetched_rows]
        return {
            "success": True,
            "row_count": len(data),
            "columns": col_names,
            "data": data,
            "execution_time_ms": execution_time_ms,
            "has_more": len(data) == max_rows,
        }
    except sqlite3.Error as e:
        return {
            "success": False,
            "error": f"SQL 執行錯誤: {e}",
        }
    finally:
        conn.close()


@mcp.tool()
def get_table_profile(table_name: str) -> dict[str, Any]:
    """對指定資料表進行統計剖析（總行數、各欄位缺失值統計與前 3 筆樣本資料）。

    Args:
        table_name: 資料表名稱（如 audit_projects, audit_findings, department_metrics, remediation_records）。
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (table_name,))
    if not cursor.fetchone():
        conn.close()
        return {"success": False, "error": f"資料表 '{table_name}' 不存在"}

    # 取得總筆數
    cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table_name};")  # noqa: S608
    total_rows = cursor.fetchone()["cnt"]

    # 取得欄位資訊
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [col["name"] for col in cursor.fetchall()]

    # 統計各欄位的空值數量
    null_counts = {}
    for col in columns:
        cursor.execute(f"SELECT COUNT(*) AS null_cnt FROM {table_name} WHERE {col} IS NULL;")  # noqa: S608
        null_counts[col] = cursor.fetchone()["null_cnt"]

    # 取得前 3 筆樣本資料
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 3;")  # noqa: S608
    sample_rows = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "success": True,
        "table_name": table_name,
        "total_rows": total_rows,
        "column_count": len(columns),
        "columns": columns,
        "null_counts": null_counts,
        "sample_rows": sample_rows,
    }


# =====================================================================
# 3. 視覺化圖表語法生成工具 (Mermaid Chart Generator)
# =====================================================================

@mcp.tool()
def generate_mermaid_chart(chart_type: str, title: str, sql_query: str) -> dict[str, Any]:
    """執行 SQL 並直接轉換為 Antigravity 支援的 Mermaid 視覺化圖表語法。
    
    支援類型：
    - 'bar' 或 'xychart'：生成 xychart-beta 統計長條圖
    - 'line'：生成 xychart-beta 趨勢折線圖
    - 'breakdown' 或 'pie'：生成 flowchart LR 風險/佔比分佈圖 (因 Antigravity 渲染器不支援原生 pie，以此最佳相容方式呈現)

    Args:
        chart_type: 圖表類型，支援 'bar', 'xychart', 'line', 'breakdown', 'pie'。
        title: 圖表標題（例如：'各風險等級缺失分佈' 或 '各部門合規通過率'）。
        sql_query: 產生圖表所需資料的 SQL 查詢（至少回傳兩欄：維度欄位, 數值欄位）。
    """
    query_res = safe_sql_query(sql_query, max_rows=50)
    if not query_res["success"]:
        return query_res

    data = query_res["data"]
    if not data:
        return {"success": False, "error": "查詢結果為空，無法產生圖表。"}

    cols = query_res["columns"]
    if len(cols) < 2:
        return {"success": False, "error": f"圖表查詢需至少提供 2 個欄位 (維度, 數值)，目前回傳: {cols}"}

    label_col, val_col = cols[0], cols[1]
    chart_type_lower = chart_type.lower()

    image_markdown = ""
    is_pie = False

    if chart_type_lower in ("breakdown", "pie", "flowchart"):
        is_pie = True
        # 計算總和以求百分比
        total_sum = sum(float(row[val_col]) for row in data if row[val_col] is not None)
        flowchart_lines = [
            "flowchart LR",
            f'    Root["{title}<br/>總計: {int(total_sum) if total_sum.is_integer() else total_sum}"]',
        ]
        
        # 節點樣式對應
        color_styles = {
            "critical": "fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c",
            "high": "#f57c00",
            "medium": "#fbc02d",
            "low": "#388e3c",
        }
        hex_colors = {
            "critical": "#d32f2f",
            "high": "#f57c00",
            "medium": "#fbc02d",
            "low": "#388e3c",
        }
        default_palette = ["#2563eb", "#7c3aed", "#db2777", "#059669", "#0891b2", "#d97706"]

        styles_to_apply = []
        qc_labels = []
        qc_data = []
        qc_colors = []

        for idx, row in enumerate(data):
            lbl = str(row[label_col]).strip()
            val = float(row[val_col]) if row[val_col] is not None else 0
            pct = round((val / total_sum * 100), 1) if total_sum > 0 else 0
            node_id = f"N{idx}"
            display_val = int(val) if val.is_integer() else val
            flowchart_lines.append(f'    Root --> {node_id}["{lbl}: {display_val} 筆 ({pct}%)"]')
            
            lbl_lower = lbl.lower()
            slice_color = default_palette[idx % len(default_palette)]
            for key, c_val in hex_colors.items():
                if key in lbl_lower:
                    slice_color = c_val
                    styles_to_apply.append(f"    style {node_id} fill:{c_val}22,stroke:{c_val},stroke-width:2px")
                    break

            qc_labels.append(f"{lbl}: {display_val} ({pct}%)")
            qc_data.append(display_val)
            qc_colors.append(slice_color)

        flowchart_lines.extend(styles_to_apply)
        chart_code = "\n".join(flowchart_lines)

        # 產生正宗圓形圓餅圖 QuickChart 圖片連結
        qc_config = {
            "type": "pie",
            "data": {
                "labels": qc_labels,
                "datasets": [{
                    "data": qc_data,
                    "backgroundColor": qc_colors
                }]
            },
            "options": {
                "plugins": {
                    "legend": {"position": "right"}
                }
            }
        }
        encoded_cfg = urllib.parse.quote(json.dumps(qc_config))
        quickchart_url = f"https://quickchart.io/chart?c={encoded_cfg}&w=520&h=280"
        image_markdown = f"![{title}]({quickchart_url})"

    elif chart_type_lower in ("bar", "xychart", "line"):
        categories = []
        values = []
        for row in data:
            raw_label = str(row[label_col]).replace('"', "")
            categories.append(f'"{raw_label}"')
            val = row[val_col]
            try:
                values.append(float(val) if val is not None else 0)
            except ValueError:
                values.append(0)

        cat_str = ", ".join(categories)
        val_str = ", ".join(str(int(v) if v.is_integer() else v) for v in values)
        
        max_val = max(values) if values else 10
        y_max = int(max_val * 1.25) + 1 if max_val > 0 else 10

        chart_plot = "line" if chart_type_lower == "line" else "bar"
        chart_code = (
            f"xychart-beta\n"
            f'    title "{title}"\n'
            f"    x-axis [{cat_str}]\n"
            f'    y-axis "{val_col}" 0 --> {y_max}\n'
            f"    {chart_plot} [{val_str}]"
        )
    else:
        return {
            "success": False,
            "error": f"不支援的圖表類型 '{chart_type}'，目前支援 'bar', 'xychart', 'line', 'breakdown', 'pie'。",
        }

    return {
        "success": True,
        "chart_type": chart_type,
        "title": title,
        "image_markdown": image_markdown,
        "mermaid_code": chart_code,
        "raw_data_summary": data,
        "usage_hint": (
            "若使用者要求『圓餅圖』，請務必直接輸出 image_markdown 以呈現真正的圓形圓餅圖！"
            if is_pie else
            "可直接在回覆中使用 ```mermaid 代碼區塊呈現此圖表！"
        ),
    }


@mcp.tool()
def export_svg_pie_chart(title: str, sql_query: str, filename: str = "audit_pie_chart.svg") -> dict[str, Any]:
    """執行 SQL 查詢並生成真正圓形的向量圓餅圖 (SVG 檔案)，純 Python 離線渲染，無須聯網。

    Args:
        title: 圖表標題（例如：'各風險等級缺失分佈'）。
        sql_query: 產生圖表所需資料的 SQL 查詢（至少包含兩欄：維度/標籤, 數值）。
        filename: 匯出的 SVG 檔案名稱（預設為 audit_pie_chart.svg，存放於專案目錄）。
    """
    query_res = safe_sql_query(sql_query, max_rows=50)
    if not query_res["success"]:
        return query_res

    data = query_res["data"]
    if not data:
        return {"success": False, "error": "查詢結果為空，無法產生圓餅圖。"}

    cols = query_res["columns"]
    if len(cols) < 2:
        return {"success": False, "error": f"圖表查詢需至少提供 2 個欄位 (維度, 數值)，目前回傳: {cols}"}

    label_col, val_col = cols[0], cols[1]

    # 清理資料與計算總和
    slices = []
    total_val = 0.0
    for row in data:
        lbl = str(row[label_col]).strip()
        val = row[val_col]
        try:
            num = float(val) if val is not None else 0.0
        except ValueError:
            num = 0.0
        if num > 0:
            slices.append({"label": lbl, "value": num})
            total_val += num

    if total_val == 0:
        return {"success": False, "error": "數值總和為 0，無法繪製圓餅圖。"}

    # 針對常見稽核關鍵字配置色彩
    color_map = {
        "critical": "#d32f2f",  # 紅
        "high": "#f57c00",      # 橙
        "medium": "#fbc02d",    # 黃
        "low": "#388e3c",       # 綠
    }
    default_palette = ["#2563eb", "#7c3aed", "#db2777", "#059669", "#0891b2", "#d97706", "#4b5563"]

    # 幾何參數
    cx, cy = 175, 160
    r = 105
    start_angle = -math.pi / 2  # 從 12 點鐘方向開始

    path_elements = []
    legend_elements = []
    legend_y = 75

    for idx, item in enumerate(slices):
        fraction = item["value"] / total_val
        angle_delta = fraction * 2 * math.pi
        end_angle = start_angle + angle_delta

        # 決定顏色
        lbl_lower = item["label"].lower()
        color = default_palette[idx % len(default_palette)]
        for k, v in color_map.items():
            if k in lbl_lower:
                color = v
                break

        # 計算弧線端點
        x1 = cx + r * math.cos(start_angle)
        y1 = cy + r * math.sin(start_angle)
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)
        large_arc = 1 if angle_delta > math.pi else 0

        # 若只有一個扇形 (100%) 畫整圓
        if len(slices) == 1:
            path_elements.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" stroke="#ffffff" stroke-width="2"/>'
            )
        else:
            path_d = f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {r} {r} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z"
            path_elements.append(
                f'<path d="{path_d}" fill="{color}" stroke="#ffffff" stroke-width="2"/>'
            )

        # 繪製圖例 (Legend)
        pct = round(fraction * 100, 1)
        val_display = int(item["value"]) if item["value"].is_integer() else item["value"]
        legend_elements.append(
            f'<rect x="315" y="{legend_y}" width="16" height="16" rx="3" fill="{color}"/>'
        )
        legend_elements.append(
            f'<text x="340" y="{legend_y + 13}" font-family="Segoe UI, sans-serif" font-size="13" fill="#333333">'
            f'{item["label"]}: {val_display} ({pct}%)'
            f'</text>'
        )
        legend_y += 28

        start_angle = end_angle

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 320" width="100%" height="100%">
    <!-- 背景卡片 -->
    <rect width="520" height="320" rx="12" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5"/>
    
    <!-- 標題 -->
    <text x="260" y="38" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="17" font-weight="bold" fill="#1e293b">
        {title}
    </text>
    
    <!-- 圓餅圖各扇區 -->
    <g>
        {"".join(path_elements)}
    </g>

    <!-- 中心裝飾白色小圓（呈現精緻甜甜圈環形圖質感） -->
    <circle cx="{cx}" cy="{cy}" r="38" fill="#ffffff"/>
    <text x="{cx}" y="{cy + 5}" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="12" font-weight="600" fill="#64748b">
        {int(total_val) if total_val.is_integer() else total_val} 筆
    </text>

    <!-- 右側圖例 -->
    <g>
        {"".join(legend_elements)}
    </g>
</svg>"""

    # 存檔至專案目錄
    safe_name = Path(filename).name
    if not safe_name.endswith(".svg"):
        safe_name += ".svg"
    out_path = Path(__file__).resolve().parent / safe_name
    out_path.write_text(svg_content, encoding="utf-8")

    return {
        "success": True,
        "title": title,
        "file_name": safe_name,
        "file_path": str(out_path),
        "total_count": total_val,
        "slices": slices,
        "message": f"已成功生成正宗圓形圓餅圖 (SVG)，檔案保存在: {safe_name}",
        "svg_snippet": svg_content[:250] + "...",
    }


@mcp.tool()
def reset_sample_database() -> dict[str, Any]:
    """將 SQLite 稽核資料庫還原為最初的預設種子資料。"""
    try:
        init_database(force_recreate=True)
        return {"success": True, "message": "已成功重置稽核資料庫為初始種子資料。"}
    except Exception as e:
        return {"success": False, "error": f"重置失敗: {e}"}


# =====================================================================
# 4. API 規格解析與智慧測資合規檢驗工具 (方案 C)
# =====================================================================

@mcp.tool()
def get_api_spec_endpoints(spec_path: str = "") -> dict[str, Any]:
    """解析並列出 OpenAPI / Swagger 規格中所有可用的 Endpoints、請求方法與 Schema 定義。

    Args:
        spec_path: OpenAPI 規格檔案路徑（留空則讀取內建的 sample_api_spec.json）。
    """
    return api_tester.get_available_endpoints(spec_path)


@mcp.tool()
def generate_smart_mock_data(schema_name: str, scenario: str = "normal", spec_path: str = "") -> dict[str, Any]:
    """依據指定 OpenAPI Schema 與測試情境生成智慧測資。

    Args:
        schema_name: 目標結構名稱（例如：'CreateFindingRequest' 或 'ReimbursementRequest'）。
        scenario: 測資情境，支援 'normal' (正常合格)、'boundary' (邊界極限值) 或 'malicious' (惡意/格式違規)。
        spec_path: 自訂 OpenAPI 規格路徑（留空則使用內建範例）。
    """
    return api_tester.generate_mock_payload(schema_name, scenario, spec_path)


@mcp.tool()
def validate_api_contract(schema_name: str, payload: dict[str, Any], spec_path: str = "") -> dict[str, Any]:
    """比對資料物件是否符合 OpenAPI Schema 定義的契約規範（檢查必填欄位、型態、限制條件與格式）。

    Args:
        schema_name: 要比對的 Schema 名稱（例如：'CreateFindingRequest' 或 'ReimbursementRequest'）。
        payload: 要進行合規性驗證的 JSON 資料物件。
        spec_path: 自訂 OpenAPI 規格路徑（留空則使用內建範例）。
    """
    return api_tester.validate_contract(schema_name, payload, spec_path)


# =====================================================================
# 5. 稽核工作底稿與正式報告自動生成工具
# =====================================================================

@mcp.tool()
def generate_audit_working_paper(project_id: str, output_format: str = "both") -> dict[str, Any]:
    """為指定稽核專案自動生成符合 IIA 標準的正式「內部稽核工作底稿 (Audit Working Paper)」。
    
    支援格式：
    - 'markdown'：輸出標準 Markdown 底稿 (.md)
    - 'docx'：輸出具備表格著色、風險等級標示與簽核欄的 Microsoft Word 底稿 (.docx)
    - 'both'：同時產出兩種格式

    Args:
        project_id: 專案代碼（例如：'PRJ-2026-005', 'PRJ-2026-001', 'PRJ-2026-002', 'PRJ-2026-003'）。
        output_format: 匯出格式，支援 'markdown', 'docx', 或 'both'。
    """
    return working_paper_generator.generate_working_paper(project_id, output_format)


# =====================================================================
# 6. 跨系統交叉比對與舞弊偵測工具 (Cross-System Fraud Detection)
# =====================================================================

@mcp.tool()
def run_fraud_detection(rule_filter: str = "all") -> dict[str, Any]:
    """執行全量「跨系統交叉比對與舞弊偵測 (Cross-System Fraud Detection)」。
    
    結合多個業務維度進行全量碰撞分析，精準找出潛在舞弊紅旗（Red Flags）：
    1. 利益衝突與關係人舞弊 (Conflict of Interest)：比對 HR 員工與 ERP 供應商之帳戶、電話或代表人。
    2. 採購拆單規避核決門檻 (Split Purchase Orders)：比對同日同採購人對同一供應商拆分低於 10 萬門檻之訂單。
    3. 幽靈帳號與離職異常存取 (Zombie Accounts)：比對 HR 離職生效日與核心系統/ERP/VPN 之後續存取與資料匯出。
    4. 假發票與重複報銷 (Duplicate Invoices)：偵測同一發票號碼被不同員工重複請款。

    【視覺化圖表輸出限制】：
    Antigravity 前端不支援 Mermaid 'pie' 語法（輸出 ```mermaid pie 會導致 Invalid mermaid header 錯誤崩潰）。
    若需視覺化呈現嚴重度分佈，請一律使用回傳之 visual_charts.image_markdown (QuickChart 圓餅圖圖片)
    或 visual_charts.xychart_mermaid (長條圖)，嚴禁自行輸出 ```mermaid pie 語法。

    Args:
        rule_filter: 執行規則過濾，支援 'all'（全量比對）、'conflict_of_interest'、'split_po'、'zombie_account'、'duplicate_invoice'。
    """
    return fraud_detector.run_cross_system_fraud_audit(rule_filter=rule_filter)


# =====================================================================
# 7. 主程式啟動入口
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    lan_ip = _get_lan_ip()
    print("=" * 65)
    print(f"🚀 啟動 Grace 稽核全功能 MCP 伺服器 (grace-audit-suite-mcp)")
    print(f"📡 本機/區網 Streamable HTTP 端點: http://{lan_ip}:{PORT}/mcp")
    print(f"📂 資料庫檔案: {DB_FILE}")
    print(f"🛠️  支援工具: [DB] get_db_overview, get_table_schema, safe_sql_query,")
    print(f"              get_table_profile, generate_mermaid_chart, export_svg_pie_chart,")
    print(f"              reset_sample_database")
    print(f"              [API] get_api_spec_endpoints, generate_smart_mock_data,")
    print(f"              validate_api_contract")
    print(f"              [DOC] generate_audit_working_paper (Markdown & Word)")
    print(f"              [FRAUD] run_fraud_detection (跨系統舞弊偵測)")
    print("=" * 65)

    # 允許跨網段與 VM IP 存取
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(transport_security=security)

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        timeout_graceful_shutdown=0,
    )
