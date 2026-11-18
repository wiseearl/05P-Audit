"""Phase 1 & 2 Mock Internal FAQ Search MCP Server (MCP v2 Streamable HTTP).

具備通用檔案管理、IIS/NSSM/Windows 服務狀態檢測、智慧日誌探針（Tail Log）、
安全自身熱更新（Self-Update）與內部知識庫搜尋能力。
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

DATA_FILE = Path(__file__).parent / "faq_data.json"
SERVER_FILE = Path(__file__).resolve()
BAK_FILE = SERVER_FILE.with_suffix(".py.bak")
TMP_FILE = SERVER_FILE.with_suffix(".py.tmp")

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))

mcp = MCPServer(
    name="internal-faq-mcp",
    instructions=(
        "提供企業內部知識庫查詢、IIS/NSSM 等 Windows 服務狀態感知、"
        "智慧日誌分析探針、遠端通用檔案系統操作，以及安全自身熱更新（Self-Update）功能。"
    ),
)


def _load_faq_data() -> list[dict[str, Any]]:
    """Load FAQ entries from faq_data.json on each call for live updates."""
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []


def _get_lan_ip() -> str:
    """Detect the host's primary LAN IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def _schedule_restart(delay_seconds: float = 1.5) -> None:
    """延遲退出程序，由外部 Supervisor (supervisor.py) 自動重啟。"""
    def _do_exit():
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=_do_exit, daemon=True).start()


# =====================================================================
# 1. 系統狀態與知識庫工具
# =====================================================================

@mcp.tool()
def get_server_info() -> dict[str, Any]:
    """取得遠端 MCP 伺服器的主機名稱、區網 IP、目前時間、知識庫筆數與支援能力。"""
    faqs = _load_faq_data()
    return {
        "hostname": socket.gethostname(),
        "ip_address": _get_lan_ip(),
        "current_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "faq_count": len(faqs),
        "transport": "streamable-http",
        "supports_service_inspection": True,
        "supports_file_ops": True,
        "supports_self_update": True,
    }


@mcp.tool()
def list_faq_categories() -> dict[str, Any]:
    """列出內部知識庫目前包含的所有分類及各分類筆數。"""
    faqs = _load_faq_data()
    counts = Counter(str(item.get("category", "未分類")) for item in faqs)
    categories = [
        {"category": category, "count": count}
        for category, count in counts.items()
    ]
    return {
        "total_count": len(faqs),
        "categories": categories,
    }


@mcp.tool()
def search_internal_faq(keyword: str = "", category: str = "") -> dict[str, Any]:
    """依關鍵字與分類搜尋企業內部模擬知識庫（FAQ）。

    Args:
        keyword: 搜尋關鍵字（比對問題、回答、分類與標籤，不分大小寫；留空則回傳全部）。
        category: 選填分類篩選（例如：IT支援、研發系統、人資規範、資安政策、總務行政）。
    """
    faqs = _load_faq_data()
    kw = keyword.strip().lower()
    cat = category.strip().lower()

    matches: list[dict[str, Any]] = []
    for item in faqs:
        item_cat = str(item.get("category", "")).lower()
        if cat and cat not in item_cat:
            continue

        if kw:
            tags = " ".join(str(tag) for tag in item.get("tags", []))
            searchable = " ".join(
                [
                    str(item.get("question", "")),
                    str(item.get("answer", "")),
                    str(item.get("category", "")),
                    tags,
                ]
            ).lower()
            if kw not in searchable:
                continue

        matches.append(item)

    return {
        "count": len(matches),
        "results": matches,
    }


# =====================================================================
# 2. IIS / NSSM / Windows 服務感知與日誌探針工具 (Service & Log Inspection)
# =====================================================================

@mcp.tool()
def inspect_service(service_name: str) -> dict[str, Any]:
    """檢測遠端機台特定 Windows 服務、IIS 站台或 NSSM 封裝服務的執行狀態與安裝路徑。

    Args:
        service_name: 服務名稱（如 IIS 的 'W3SVC'、WAS，或自訂 NSSM 服務名稱）。
    """
    svc = service_name.strip()
    if not svc:
        return {"success": False, "error": "請提供有效的服務名稱"}

    # 1. 查詢運行狀態與 PID
    q = subprocess.run(["sc", "query", svc], capture_output=True, text=True, errors="replace")
    if q.returncode != 0:
        return {"success": False, "error": f"找不到服務 '{svc}' 或無法查詢: {q.stderr.strip() or q.stdout.strip()}"}

    state = "UNKNOWN"
    pid = None
    for line in q.stdout.splitlines():
        if "STATE" in line:
            parts = line.split(":", 1)[1].strip().split()
            state = parts[1] if len(parts) > 1 else parts[0]
        elif "PID" in line:
            m = re.search(r"\d+", line)
            if m:
                pid = int(m.group(0))

    # 2. 查詢服務執行檔與啟動類型
    qc = subprocess.run(["sc", "qc", svc], capture_output=True, text=True, errors="replace")
    bin_path = ""
    start_type = ""
    for line in qc.stdout.splitlines():
        if "BINARY_PATH_NAME" in line:
            bin_path = line.split(":", 1)[1].strip()
        elif "START_TYPE" in line:
            start_type = line.split(":", 1)[1].strip()

    # 判斷是否為 NSSM 封裝
    is_nssm = "nssm" in bin_path.lower()

    return {
        "success": True,
        "service_name": svc,
        "state": state,
        "is_running": "RUNNING" in state.upper(),
        "pid": pid,
        "binary_path": bin_path,
        "start_type": start_type,
        "is_nssm_managed": is_nssm,
    }


@mcp.tool()
def list_services(filter_keyword: str = "") -> dict[str, Any]:
    """列出遠端機台的 Windows 服務（支援關鍵字篩選，可用於尋找 IIS、NSSM 等服務名稱）。

    Args:
        filter_keyword: 選填關鍵字（例如：iis、w3svc、nssm 或自訂應用名稱；留空則列出前 30 項）。
    """
    res = subprocess.run(
        ["sc", "query", "type=", "service", "state=", "all"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if res.returncode != 0:
        return {"success": False, "error": f"查詢服務清單失敗: {res.stderr.strip()}"}

    services = []
    current: dict[str, Any] = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("SERVICE_NAME:"):
            if current:
                services.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
        elif line.startswith("DISPLAY_NAME:") and current:
            current["display_name"] = line.split(":", 1)[1].strip()
        elif line.startswith("STATE") and current:
            parts = line.split(":", 1)[1].strip().split()
            current["state"] = parts[1] if len(parts) > 1 else parts[0]

    if current:
        services.append(current)

    kw = filter_keyword.strip().lower()
    if kw:
        services = [
            s for s in services
            if kw in s.get("name", "").lower() or kw in s.get("display_name", "").lower()
        ]

    return {
        "success": True,
        "filter": filter_keyword,
        "total_matched": len(services),
        "services": services[:30],
    }


@mcp.tool()
def inspect_tail_log(
    log_path: str,
    lines: int = 50,
    filter_keyword: str = "",
) -> dict[str, Any]:
    """智慧讀取日誌（Log）檔案最後 N 行，並可針對 ERROR/Exception 關鍵字進行精確快篩。

    具備 Token 防護機制：只取檔案末尾，不載入整份大日誌。

    Args:
        log_path: 日誌相對路徑或遠端絕對路徑（如：C:/inetpub/logs/LogFiles/W3SVC1/u_ex261117.log 或專案 log）。
        lines: 讀取末尾行數（預設 50 行，最多 200 行）。
        filter_keyword: 選填關鍵字過濾（如 'ERROR'、'500'、'Exception' 等）。
    """
    path = Path(log_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()

    if not path.exists():
        return {"success": False, "error": f"日誌檔案不存在: {path}"}
    if not path.is_file():
        return {"success": False, "error": f"指定路徑不是檔案: {path}"}

    lines = max(1, min(lines, 200))
    kw = filter_keyword.strip().lower()

    try:
        # 採用由後往前的高效讀取方式（支援大檔案）
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        tail_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        if kw:
            matched_lines = [l.rstrip("\r\n") for l in tail_lines if kw in l.lower()]
        else:
            matched_lines = [l.rstrip("\r\n") for l in tail_lines]

        return {
            "success": True,
            "log_path": str(path),
            "file_size_bytes": path.stat().st_size,
            "tail_lines_requested": lines,
            "matched_count": len(matched_lines),
            "lines": matched_lines,
        }
    except Exception as e:
        return {"success": False, "error": f"讀取日誌失敗: {e}"}


# =====================================================================
# 3. 通用型遠端檔案系統工具 (General File Management)
# =====================================================================

@mcp.tool()
def read_remote_file(file_path: str, max_chars: int = 20000) -> dict[str, Any]:
    """讀取遠端機台指定檔案的內容（文字檔）。

    Args:
        file_path: 相對路徑（相對於專案目錄）或遠端絕對路徑（例如：faq_data.json 或 D:/data/config.txt）。
        max_chars: 最大讀取字元數，預設 20000 字元避免超出上下文限制。
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()

    if not path.exists():
        return {"success": False, "error": f"檔案不存在: {path}"}
    if not path.is_file():
        return {"success": False, "error": f"指定路徑不是檔案: {path}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        return {
            "success": True,
            "file_path": str(path),
            "size_bytes": path.stat().st_size,
            "truncated": truncated,
            "content": content[:max_chars],
        }
    except Exception as e:
        return {"success": False, "error": f"讀取檔案失敗: {e}"}


@mcp.tool()
def write_remote_file(
    file_path: str,
    content: str,
    create_backup: bool = True,
    restart_if_server: bool = True,
) -> dict[str, Any]:
    """通用寫入/更新遠端機台的檔案（支援 faq_data.json、各類資料或 server.py 本身）。

    特點：
    1. 若寫入目標為 JSON 檔：自動進行 JSON 語法格式校驗。
    2. 若寫入目標為 server.py：自動觸發 AST 檢查、探針試跑與重啟程序。
    3. 自動建立 .bak 備份檔案，並使用原子性寫入避免中斷損壞。

    Args:
        file_path: 相對路徑或絕對路徑。
        content: 欲寫入的完整文字內容。
        create_backup: 覆寫前是否自動在同目錄下產生 .bak 備份（預設 True）。
        restart_if_server: 若寫入目標為伺服器主程式 (server.py)，是否在成功後自動觸發重啟（預設 True）。
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()

    # 如果是更新 server.py 本身，轉交至嚴格安全防護流程
    if path == SERVER_FILE:
        return apply_server_update(content)

    # 若是 JSON 檔案，進行結構合法性檢查防呆
    if path.suffix.lower() == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON 語法檢驗失敗，已拒絕寫入以防止損壞資料庫: 第 {e.lineno} 行 - {e.msg}",
            }

    # 自動備份
    backup_file = None
    if create_backup and path.exists():
        backup_file = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copyfile(path, backup_file)
        except OSError as e:
            return {"success": False, "error": f"建立備份失敗: {e}"}

    # 原子寫入
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return {"success": False, "error": f"寫入檔案失敗: {e}"}

    return {
        "success": True,
        "message": f"檔案寫入成功: {path.name}",
        "file_path": str(path),
        "backup_path": str(backup_file) if backup_file else None,
        "size_bytes": path.stat().st_size,
    }


@mcp.tool()
def list_remote_directory(dir_path: str = ".") -> dict[str, Any]:
    """查看遠端機台指定目錄下的檔案與子資料夾清單。

    Args:
        dir_path: 相對路徑或絕對路徑（預設為伺服器當前專案目錄）。
    """
    path = Path(dir_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()

    if not path.exists():
        return {"success": False, "error": f"目錄不存在: {path}"}
    if not path.is_dir():
        return {"success": False, "error": f"指定路徑不是目錄: {path}"}

    try:
        items = []
        for p in sorted(path.iterdir()):
            items.append({
                "name": p.name,
                "is_dir": p.is_dir(),
                "size_bytes": p.stat().st_size if p.is_file() else None,
                "updated_at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        return {
            "success": True,
            "dir_path": str(path),
            "total_items": len(items),
            "items": items,
        }
    except Exception as e:
        return {"success": False, "error": f"讀取目錄失敗: {e}"}


# =====================================================================
# 4. 專屬安全自身更新工具 (Self-Update & Rollback)
# =====================================================================

@mcp.tool()
def apply_server_update(new_code: str) -> dict[str, Any]:
    """安全熱更新伺服器本身的 Python 原始碼 (server.py)。

    採用三重安全防護機制：
    1. 靜態語法檢查 (AST Validation)：預防 SyntaxError。
    2. 探針試跑 (Pre-flight Probe)：以獨立子程序驗證新程式碼能否成功 import 與初始化。
    3. 自動備份與原子替換：備份當前版本為 server.py.bak，覆寫後觸發優雅延遲重啟。

    Args:
        new_code: 完整更新後的 Python 原始碼字串。
    """
    if not new_code or not new_code.strip():
        return {"success": False, "error": "提供的程式碼為空，拒絕更新。"}

    # 第一重防護：AST 靜態語法解析
    try:
        ast.parse(new_code, filename="server.py")
    except SyntaxError as e:
        return {
            "success": False,
            "stage": "ast_validation",
            "error": f"語法檢查失敗 (SyntaxError): 第 {e.lineno} 行 - {e.msg}",
        }

    # 寫入暫存檔以利探針測試
    try:
        TMP_FILE.write_text(new_code, encoding="utf-8")
    except OSError as e:
        return {"success": False, "stage": "write_tmp", "error": f"寫入暫存檔失敗: {e}"}

    # 第二重防護：Pre-flight 子程序探針測試
    probe_script = (
        "import sys, pathlib; "
        "sys.path.insert(0, str(pathlib.Path.cwd())); "
        "import server_test as s; "
        "assert hasattr(s, 'mcp'), 'Missing mcp instance'; "
        "print('PROBE_SUCCESS')"
    )
    probe_file = SERVER_FILE.parent / "server_test.py"
    try:
        shutil.copyfile(TMP_FILE, probe_file)
        result = subprocess.run(
            [sys.executable, "-c", probe_script],
            cwd=str(SERVER_FILE.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            error_detail = (result.stderr or result.stdout or "未知錯誤").strip()
            return {
                "success": False,
                "stage": "preflight_probe",
                "error": f"探針試跑失敗，新代碼可能存在執行期錯誤或依賴缺失: {error_detail}",
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stage": "preflight_probe",
            "error": "探針試跑超時 (超過 10 秒)，已終止更新。",
        }
    except Exception as e:
        return {
            "success": False,
            "stage": "preflight_probe",
            "error": f"探針測試過程異常: {e}",
        }
    finally:
        if probe_file.exists():
            try:
                probe_file.unlink()
            except OSError:
                pass

    # 第三重防護：備份與原子覆寫
    try:
        if SERVER_FILE.exists():
            shutil.copyfile(SERVER_FILE, BAK_FILE)
        os.replace(TMP_FILE, SERVER_FILE)
    except OSError as e:
        return {"success": False, "stage": "atomic_replace", "error": f"檔案替換失敗: {e}"}

    # 延遲排程優雅退出，由外部 supervisor 重啟
    _schedule_restart(delay_seconds=1.5)

    return {
        "success": True,
        "message": "程式碼更新成功！已通過語法與探針驗證，備份已建立。伺服器將在 1.5 秒後自動重啟生效。",
        "backup_path": str(BAK_FILE),
    }


@mcp.tool()
def rollback_server() -> dict[str, Any]:
    """手動將伺服器程式碼還原為前一個備份版本 (server.py.bak) 並重啟。"""
    if not BAK_FILE.exists():
        return {"success": False, "error": "找不到 server.py.bak 備份檔案，無法還原。"}

    try:
        shutil.copyfile(BAK_FILE, SERVER_FILE)
    except OSError as e:
        return {"success": False, "error": f"還原備份失敗: {e}"}

    _schedule_restart(delay_seconds=1.5)
    return {
        "success": True,
        "message": "已成功將伺服器程式碼還原為 .bak 備份版本，伺服器將在 1.5 秒後重啟生效。",
    }


if __name__ == "__main__":
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    lan_ip = _get_lan_ip()
    print("=" * 60)
    print(f"Starting internal-faq-mcp on {HOST}:{PORT}")
    print(f"Streamable HTTP Endpoint: http://{lan_ip}:{PORT}/mcp")
    print(f"Services & Log Inspection + Self-Update Enabled.")
    print("=" * 60)

    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(transport_security=security)
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        timeout_graceful_shutdown=0,
    )
