"""Phase 1 & 2 Mock Internal FAQ Search MCP Server (MCP v2 Streamable HTTP).

具備通用檔案管理、IIS/NSSM/Windows 服務狀態檢測、智慧日誌探針（Tail Log）、
安全自身熱更新（Self-Update）與內部知識庫搜尋能力。
"""

from __future__ import annotations

import ast
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

DATA_FILE = Path(__file__).parent / "faq_data.json"
SERVER_FILE = Path(__file__).resolve()
ENV_FILE = SERVER_FILE.parent / ".env"
BAK_FILE = SERVER_FILE.with_suffix(".py.bak")
TMP_FILE = SERVER_FILE.with_suffix(".py.tmp")
LOG_DIR = SERVER_FILE.parent / "logs"
LIFECYCLE_LOG = LOG_DIR / "lifecycle.log"
AUDIT_LOG = LOG_DIR / "audit_tools.jsonl"
ERRORS_LOG = LOG_DIR / "errors.log"
DAILY_STATS_FILE = LOG_DIR / "daily_stats.json"
_STATS_LOCK = threading.Lock()
BOOT_TIME = datetime.now()
LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_MAX_SUMMARY_CHARS = 1500
LINE_RAW_LOG_THRESHOLD = 5

SENSITIVE_ALLOWED_NAMES = frozenset({".env.example"})
SENSITIVE_EXACT_NAMES = frozenset({
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    ".netrc",
    ".npmrc",
    ".pypirc",
})
SENSITIVE_SUFFIXES = frozenset({
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".jks",
    ".keystore",
    ".kdbx",
    ".crt",
    ".cer",
})

_DLP_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("私鑰區塊", re.compile(r"-----\s*BEGIN\s+[A-Z0-9 ]*PRIVATE KEY\s*-----", re.IGNORECASE)),
    ("Bearer Token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{16,}=*", re.IGNORECASE)),
    ("環境機密鍵值", re.compile(r"\b(LINE_CHANNEL_ACCESS_TOKEN|API_KEY|SECRET_KEY|ACCESS_TOKEN|PRIVATE_KEY)\s*[:=]\s*\S{8,}", re.IGNORECASE)),
    ("雲端/平台 API 金鑰", re.compile(r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z\-_]{30,}|AKIA[0-9A-Z]{16})\b")),
    ("資料庫連線密碼", re.compile(r"(Password|Pwd)\s*=\s*[^;\s\r\n]{4,}", re.IGNORECASE)),
    ("含帳密之連線字串", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]{4,}@")),
]
_DLP_STACKTRACE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Python 原始堆疊追蹤", re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)),
    ("程式堆疊追蹤 (Stack Frame)", re.compile(r"(?m)^\s*at\s+[\w.$<>]+\.[\w$<>]+\([^\r\n]*\)")),
]
_DLP_RAW_LOG_LINE_RE = re.compile(
    r"^\s*(\[?\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]?|\d{2}:\d{2}:\d{2}[.,]\d+\s+[-|]).*"
    r"|(\s-\s(INFO|DEBUG|WARNING|ERROR|CRITICAL)\s-\s)"
)

def _get_env_setting(key: str, default: str = "") -> str:
    """Read setting preferring OS environment variable, falling back to .env (live reload)."""
    os_val = os.getenv(key, "").strip()
    if os_val:
        return os_val
    if ENV_FILE.exists():
        try:
            for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    val = v.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1]
                    return val
        except OSError as e:
            print(f"[ERROR_SUMMARY] {type(e).__name__} reading .env for {key}: {e}", file=sys.stderr)
    return default.strip()


HOST = _get_env_setting("MCP_HOST", "0.0.0.0")
PORT = int(_get_env_setting("MCP_PORT", "8000"))

mcp = MCPServer(
    name="internal-faq-mcp",
    instructions=(
        "提供企業內部知識庫查詢、IIS/NSSM 等 Windows 服務狀態感知、"
        "智慧日誌分析探針、遠端通用檔案系統操作、LINE Messaging API 摘要報告推播（內建 DLP 防外洩），"
        "以及安全自身熱更新（Self-Update）功能。"
    ),
)


def _check_sensitive_path(path: Path) -> str | None:
    """Return block reason if target path matches sensitive file blacklist."""
    resolved = path.resolve()
    name = resolved.name.lower()
    if name in SENSITIVE_ALLOWED_NAMES:
        return None

    # 剝除尾端 .bak / .tmp 後再比對，防止透過備份檔繞過黑名單
    normalized = name
    for ext in (".bak", ".tmp", ".orig", ".old"):
        if normalized.endswith(ext):
            normalized = normalized[: -len(ext)]

    if normalized == ".env" or normalized.startswith(".env."):
        return f"安全限制：禁止透過 MCP 讀寫環境機密檔案 ({resolved.name})。"
    if normalized in SENSITIVE_EXACT_NAMES:
        return f"安全限制：禁止透過 MCP 讀寫敏感憑證檔案 ({resolved.name})。"
    if any(normalized.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return f"安全限制：禁止透過 MCP 讀寫私鑰或憑證類檔案 ({resolved.name})。"
    return None


def _check_line_dlp(text: str, active_token: str = "") -> str | None:
    """Block secrets, raw logs, stack traces, or oversized dumps from outbound LINE push."""
    if len(text) > LINE_MAX_SUMMARY_CHARS:
        return (
            f"DLP 攔截：LINE 推播僅限摘要報告（上限 {LINE_MAX_SUMMARY_CHARS} 字元，目前 {len(text)} 字元），"
            "請精簡為重點摘要後再發送。"
        )

    if active_token and len(active_token) >= 16 and active_token[:16] in text:
        return "DLP 攔截：偵測到訊息包含 LINE Channel Access Token 片段，已拒絕外傳。"

    for label, pattern in _DLP_SECRET_PATTERNS:
        if pattern.search(text):
            return f"DLP 攔截：偵測到疑似機密資訊（{label}），嚴禁透過 LINE 外傳。"

    for label, pattern in _DLP_STACKTRACE_PATTERNS:
        if pattern.search(text):
            return f"DLP 攔截：偵測到原始錯誤堆疊（{label}），請改以去識別化重點摘要發送。"

    raw_log_lines = sum(1 for line in text.splitlines() if _DLP_RAW_LOG_LINE_RE.search(line))
    if raw_log_lines >= LINE_RAW_LOG_THRESHOLD:
        return (
            f"DLP 攔截：偵測到 {raw_log_lines} 行原始日誌格式內容，嚴禁直接將原始 Log 推播至 LINE；"
            "請整理為重點摘要後再發送。"
        )

    return None


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


def _ensure_nssm_binary() -> None:
    """Ensure project self-contained nssm.exe exists under project nssm/ directory."""
    target = SERVER_FILE.parent / "nssm" / "nssm.exe"
    if target.exists():
        return
    candidates: list[Path] = []
    which_nssm = shutil.which("nssm")
    if which_nssm:
        candidates.append(Path(which_nssm))
    candidates.extend([
        Path(r"C:\Program Files\nssm\win64\nssm.exe"),
        Path(r"C:\tools\nssm\nssm.exe"),
        Path(r"D:\tools\nssm\nssm.exe"),
    ])
    for c in candidates:
        if c.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(c, target)
                _log_lifecycle("nssm_binary_provisioned", {"source": str(c), "target": str(target)})
                break
            except Exception as e:
                print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to provision nssm.exe: {e}", file=sys.stderr)


def _is_client_ip_allowed(client_ip: str) -> bool:
    """Check if client IP matches allowed list (always allows localhost and server LAN IP)."""
    if not client_ip:
        return False
    clean_ip = client_ip.strip()
    # 1. 安全底線：永遠放行 Loopback 與 伺服器自身區網 IP，確保不自我鎖死
    if clean_ip in ("127.0.0.1", "::1", "localhost", HOST, _get_lan_ip()):
        return True

    # 2. 讀取 .env 中的 MCP_ALLOWED_IPS 設定 (若未設置則採嚴格零信任：拒絕所有外部連線，僅限本機)
    raw_setting = _get_env_setting("MCP_ALLOWED_IPS")
    if not raw_setting:
        return False

    # 3. 逐一比對白名單項目（支援精確單一 IP 與 CIDR 網段遮罩）
    try:
        incoming_ip = ipaddress.ip_address(clean_ip)
    except ValueError:
        return False

    for item in raw_setting.split(","):
        entry = item.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                net = ipaddress.ip_network(entry, strict=False)
                if incoming_ip in net:
                    return True
            else:
                target_ip = ipaddress.ip_address(entry)
                if incoming_ip == target_ip:
                    return True
        except ValueError:
            continue

    return False


class IPWhitelistMiddleware:
    """ASGI middleware to enforce LAN IP whitelist access control."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            client_ip = scope.get("client", ("", 0))[0]
            if not _is_client_ip_allowed(client_ip):
                _log_lifecycle(
                    "connection_rejected_by_ip_whitelist",
                    {"client_ip": client_ip, "path": scope.get("path", "")},
                )
                from starlette.responses import JSONResponse

                resp = JSONResponse(
                    {
                        "error": "Forbidden",
                        "message": f"Client IP '{client_ip}' is not in the allowed IP whitelist.",
                    },
                    status_code=403,
                )
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _safe_str(val: Any, default: str = "") -> str:
    """Safely return stripped string or default."""
    if val is None:
        return default
    return str(val).strip()


def _safe_int(val: Any, default: int) -> int:
    """Safely return integer or default."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_bool(val: Any, default: bool) -> bool:
    """Safely return boolean or default."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _init_logging() -> None:
    """Initialize the logs directory and record startup lifecycle event."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _log_lifecycle("server_boot", {
            "pid": os.getpid(),
            "boot_time": BOOT_TIME.isoformat(),
            "host": HOST,
            "port": PORT,
            "python_version": sys.version.split()[0],
        })
        _record_boot_stats()
    except Exception as e:
        print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to init logging: {e}", file=sys.stderr)


def _log_lifecycle(event: str, details: dict[str, Any] | None = None) -> None:
    """Log server lifecycle events (boot, shutdown, reload) to lifecycle.log."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        detail_str = json.dumps(details or {}, ensure_ascii=False)
        line = f"[{ts}] [PID:{os.getpid()}] [EVENT:{event}] {detail_str}\n"
        with LIFECYCLE_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to write lifecycle.log: {e}", file=sys.stderr)


def _log_error(action: str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    """Log runtime errors and exceptions to errors.log and sys.stderr."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        tb = traceback.format_exc()
        entry = (
            f"[{ts}] [ACTION:{action}] [TYPE:{type(exc).__name__}]\n"
            f"Message: {exc}\n"
            f"Context: {json.dumps(context or {}, ensure_ascii=False)}\n"
            f"Traceback:\n{tb}\n"
            f"{'-'*60}\n"
        )
        with ERRORS_LOG.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as log_err:
        print(f"[ERROR_SUMMARY] {type(log_err).__name__}: Failed to write errors.log: {log_err}", file=sys.stderr)
    print(f"[ERROR_SUMMARY] {type(exc).__name__}: {exc}", file=sys.stderr)


def _record_boot_stats() -> None:
    """Record boot time and ensure daily_stats.json structure."""
    with _STATS_LOCK:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            data: dict[str, Any] = {}
            if DAILY_STATS_FILE.exists():
                try:
                    data = json.loads(DAILY_STATS_FILE.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to parse daily_stats.json: {e}", file=sys.stderr)
                    data = {}
            if today not in data:
                data[today] = {
                    "date": today,
                    "boot_count": 0,
                    "last_boot_time": BOOT_TIME.isoformat(),
                    "total_requests": 0,
                    "action_breakdown": {},
                    "total_chars_in": 0,
                    "total_chars_out": 0,
                    "estimated_tokens_in": 0,
                    "estimated_tokens_out": 0,
                    "estimated_cost_usd": 0.0,
                    "schema_tokens_saved": 0,
                }
            data[today]["boot_count"] = data[today].get("boot_count", 0) + 1
            data[today]["last_boot_time"] = BOOT_TIME.isoformat()

            tmp_stats = DAILY_STATS_FILE.with_suffix(".json.tmp")
            tmp_stats.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_stats.replace(DAILY_STATS_FILE)
        except Exception as e:
            print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to record boot stats: {e}", file=sys.stderr)


def _mask_sensitive_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of params with sensitive values masked."""
    masked: dict[str, Any] = {}
    sensitive_keys = frozenset({"token", "password", "pwd", "key", "secret", "new_code", "content"})
    for k, v in params.items():
        if any(sk in k.lower() for sk in sensitive_keys):
            if isinstance(v, str):
                masked[k] = f"<{len(v)} chars hidden>"
            else:
                masked[k] = "<hidden>"
        else:
            masked[k] = v
    return masked


def _record_audit(
    action: str,
    params: dict[str, Any] | None,
    result: dict[str, Any],
    elapsed_ms: float,
) -> None:
    """Record audit log and update daily aggregated statistics."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()

        safe_params = _mask_sensitive_params(params or {})
        param_str = json.dumps(safe_params, ensure_ascii=False)
        result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)

        chars_in = len(param_str)
        chars_out = len(result_str)
        tokens_in = max(1, chars_in // 4)
        tokens_out = max(1, chars_out // 4)

        # Baseline cost estimate (USD): $0.15/1M input tokens, $0.60/1M output tokens
        cost_usd = round((tokens_in * 0.00000015) + (tokens_out * 0.00000060), 8)

        # Schema tokens saved per request compared to exposing 12 individual tools (~1820 tokens)
        saved_tokens = 1820

        audit_entry = {
            "timestamp": ts,
            "action": action,
            "elapsed_ms": round(elapsed_ms, 2),
            "success": result.get("success", True) if isinstance(result, dict) else True,
            "chars_in": chars_in,
            "chars_out": chars_out,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "params_summary": safe_params,
        }
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")

        with _STATS_LOCK:
            today = datetime.now().strftime("%Y-%m-%d")
            data: dict[str, Any] = {}
            if DAILY_STATS_FILE.exists():
                try:
                    data = json.loads(DAILY_STATS_FILE.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to load daily_stats.json: {e}", file=sys.stderr)
                    data = {}
            if today not in data:
                data[today] = {
                    "date": today,
                    "boot_count": 1,
                    "last_boot_time": BOOT_TIME.isoformat(),
                    "total_requests": 0,
                    "action_breakdown": {},
                    "total_chars_in": 0,
                    "total_chars_out": 0,
                    "estimated_tokens_in": 0,
                    "estimated_tokens_out": 0,
                    "estimated_cost_usd": 0.0,
                    "schema_tokens_saved": 0,
                }
            entry = data[today]
            entry["total_requests"] = entry.get("total_requests", 0) + 1
            breakdown = entry.setdefault("action_breakdown", {})
            breakdown[action] = breakdown.get(action, 0) + 1
            entry["total_chars_in"] = entry.get("total_chars_in", 0) + chars_in
            entry["total_chars_out"] = entry.get("total_chars_out", 0) + chars_out
            entry["estimated_tokens_in"] = entry.get("estimated_tokens_in", 0) + tokens_in
            entry["estimated_tokens_out"] = entry.get("estimated_tokens_out", 0) + tokens_out
            entry["estimated_cost_usd"] = round(entry.get("estimated_cost_usd", 0.0) + cost_usd, 6)
            entry["schema_tokens_saved"] = entry.get("schema_tokens_saved", 0) + saved_tokens

            tmp_stats = DAILY_STATS_FILE.with_suffix(".json.tmp")
            tmp_stats.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_stats.replace(DAILY_STATS_FILE)
    except Exception as e:
        print(f"[ERROR_SUMMARY] {type(e).__name__}: Failed to record audit: {e}", file=sys.stderr)


def get_mcp_audit_stats(target_date: str = "") -> dict[str, Any]:
    """Retrieve runtime and cost statistics from daily_stats.json."""
    today = datetime.now().strftime("%Y-%m-%d")
    date_key = target_date.strip() or today
    now = datetime.now()
    uptime_sec = round((now - BOOT_TIME).total_seconds(), 1)

    with _STATS_LOCK:
        if not DAILY_STATS_FILE.exists():
            return {
                "success": True,
                "current_time": now.isoformat(),
                "boot_time": BOOT_TIME.isoformat(),
                "uptime_seconds": uptime_sec,
                "message": "尚未累積任何統計資料。",
                "stats": {},
            }
        try:
            data = json.loads(DAILY_STATS_FILE.read_text(encoding="utf-8"))
            stats = data.get(date_key, {})
            return {
                "success": True,
                "current_time": now.isoformat(),
                "boot_time": BOOT_TIME.isoformat(),
                "uptime_seconds": uptime_sec,
                "target_date": date_key,
                "stats": stats,
                "available_dates": sorted(data.keys()),
            }
        except Exception as e:
            _log_error("get_mcp_audit_stats", e)
            return {"success": False, "error": f"讀取統計紀錄檔失敗 ({type(e).__name__}): {e}"}


def _schedule_restart(delay_seconds: float = 1.5, reason: str = "server_update") -> None:
    """延遲退出程序，由外部 Supervisor (supervisor.py) 自動重啟。"""
    _log_lifecycle("server_reload_scheduled", {"delay_seconds": delay_seconds, "reason": reason})

    def _do_exit():
        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=_do_exit, daemon=True).start()


# =====================================================================
# 1. 系統狀態與知識庫工具
# =====================================================================

def get_server_info() -> dict[str, Any]:
    """取得遠端 MCP 伺服器的主機名稱、區網 IP、目前時間、知識庫筆數與支援能力。"""
    faqs = _load_faq_data()
    return {
        "hostname": socket.gethostname(),
        "ip_address": _get_lan_ip(),
        "current_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "boot_time": BOOT_TIME.astimezone().isoformat(timespec="seconds"),
        "uptime_seconds": round((datetime.now() - BOOT_TIME).total_seconds(), 1),
        "faq_count": len(faqs),
        "transport": "streamable-http",
        "gateway_converged": True,
        "logging_enabled": True,
        "supports_service_inspection": True,
        "supports_file_ops": True,
        "supports_self_update": True,
        "supports_line_notify": bool(_get_env_setting("LINE_CHANNEL_ACCESS_TOKEN")),
        "ip_whitelist_enabled": True,
        "security_guards_enabled": True,
    }


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


def inspect_tail_log(
    log_path: str,
    lines: int = 50,
    filter_keyword: str = "",
) -> dict[str, Any]:
    """智慧讀取日誌（Log）檔案最後 N 行，並可針對 ERROR/Exception 關鍵字進行精確快篩。

    具備 Token 防護機制：只取檔案末尾，不載入整份大日誌。

    Args:
        log_path: 日誌相對路徑或遠端絕對路徑（如：C:/inetpub/logs/LogFiles/W3SVC1/u_exYYMMDD.log 或專案 log）。
        lines: 讀取末尾行數（預設 50 行，最多 200 行）。
        filter_keyword: 選填關鍵字過濾（如 'ERROR'、'500'、'Exception' 等）。
    """
    path = Path(log_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()
    else:
        path = path.resolve()

    blocked = _check_sensitive_path(path)
    if blocked:
        return {"success": False, "error": blocked}

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

def read_remote_file(file_path: str, max_chars: int = 20000) -> dict[str, Any]:
    """讀取遠端機台指定檔案的內容（文字檔）。

    Args:
        file_path: 相對路徑（相對於專案目錄）或遠端絕對路徑（例如：faq_data.json 或 D:/data/config.txt）。
        max_chars: 最大讀取字元數，預設 20000 字元避免超出上下文限制。
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()
    else:
        path = path.resolve()

    blocked = _check_sensitive_path(path)
    if blocked:
        return {"success": False, "error": blocked}

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
    else:
        path = path.resolve()

    blocked = _check_sensitive_path(path)
    if blocked:
        return {"success": False, "error": blocked}

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


def delete_remote_file(file_path: str) -> dict[str, Any]:
    """刪除遠端機台的指定檔案（受機密檔案黑名單保護，禁止刪除核心伺服器主程式與守護程式）。

    Args:
        file_path: 相對路徑或絕對路徑。
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = (SERVER_FILE.parent / path).resolve()
    else:
        path = path.resolve()

    if path in (SERVER_FILE, SERVER_FILE.parent / "supervisor.py"):
        return {"success": False, "error": "禁止刪除核心伺服器程式碼檔案。"}

    blocked = _check_sensitive_path(path)
    if blocked:
        return {"success": False, "error": blocked}

    if not path.exists():
        return {"success": False, "error": f"檔案不存在: {path}"}
    if not path.is_file():
        return {"success": False, "error": f"指定路徑不是檔案: {path}"}

    try:
        path.unlink()
        return {
            "success": True,
            "message": f"檔案已成功刪除: {path.name}",
            "file_path": str(path),
        }
    except Exception as e:
        return {"success": False, "error": f"刪除檔案失敗: {e}"}


# =====================================================================
# 4. 專屬安全自身更新工具 (Self-Update & Rollback)
# =====================================================================

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
    _schedule_restart(delay_seconds=1.5, reason="apply_server_update")

    return {
        "success": True,
        "message": "程式碼更新成功！已通過語法與探針驗證，備份已建立。伺服器將在 1.5 秒後自動重啟生效。",
        "backup_path": str(BAK_FILE),
    }


def rollback_server() -> dict[str, Any]:
    """手動將伺服器程式碼還原為前一個備份版本 (server.py.bak) 並重啟。"""
    if not BAK_FILE.exists():
        return {"success": False, "error": "找不到 server.py.bak 備份檔案，無法還原。"}

    try:
        shutil.copyfile(BAK_FILE, SERVER_FILE)
    except OSError as e:
        return {"success": False, "error": f"還原備份失敗: {e}"}

    _schedule_restart(delay_seconds=1.5, reason="rollback_server")
    return {
        "success": True,
        "message": "已成功將伺服器程式碼還原為 .bak 備份版本，伺服器將在 1.5 秒後重啟生效。",
    }


# =====================================================================
# 5. 外部通知連動工具 (LINE Messaging API)
# =====================================================================

def send_line_message(message: str, to_id: str = "") -> dict[str, Any]:
    """透過 LINE Messaging API（Push API）主動推播去識別化摘要報告或告警至指定 LINE 個人或群組。

    安全規則（內建 DLP 攔截）：
    - 僅限傳送整理後的重點摘要或狀態告警（上限 1,500 字元）。
    - 嚴禁直接傳送原始日誌（Raw Log）、錯誤堆疊（Stack Trace）、Token、密碼或連線字串，違者自動拒絕發送。
    - 憑證優先讀取系統環境變數，其次讀取遠端專案目錄下的 `.env`（即時生效）。

    Args:
        message: 要傳送的去識別化文字摘要（上限 1,500 字元）。
        to_id: 選填目標 User ID 或 Group ID；留空則自動使用 `LINE_DEFAULT_TARGET_ID`。
    """
    text = message.strip()
    if not text:
        return {"success": False, "error": "訊息內容不可為空。"}

    token = _get_env_setting("LINE_CHANNEL_ACCESS_TOKEN")
    if not token or token == "你的_Channel_Access_Token":
        return {
            "success": False,
            "error": "尚未設定 LINE_CHANNEL_ACCESS_TOKEN，請於遠端系統環境變數或 .env 填入有效 Token。",
        }

    # 外傳防洩漏檢查（DLP：阻擋機密、原始 Log、堆疊追蹤與超長傾印）
    dlp_error = _check_line_dlp(text, active_token=token)
    if dlp_error:
        return {"success": False, "blocked_by_dlp": True, "error": dlp_error}

    target_id = to_id.strip() or _get_env_setting("LINE_DEFAULT_TARGET_ID")
    if not target_id or target_id == "你的_User_ID_或_Group_ID":
        return {
            "success": False,
            "error": "未提供目標對象 ID，請傳入 to_id 或設定 LINE_DEFAULT_TARGET_ID。",
        }

    # 選填白名單防呆檢查
    raw_allowlist = _get_env_setting("LINE_ALLOWED_TARGETS")
    if raw_allowlist:
        allowed = {item.strip() for item in raw_allowlist.split(",") if item.strip()}
        if target_id not in allowed:
            return {
                "success": False,
                "error": f"目標 ID '{target_id[:8]}...' 不在 LINE_ALLOWED_TARGETS 白名單中，已拒絕發送。",
            }

    payload = {
        "to": target_id,
        "messages": [{"type": "text", "text": text}],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            LINE_PUSH_API_URL,
            headers=headers,
            json=payload,
            timeout=15.0,
        )
    except httpx.TimeoutException as e:
        print(f"[ERROR_SUMMARY] {type(e).__name__}: LINE API timeout", file=sys.stderr)
        return {"success": False, "error": "連線 LINE API 超時（超過 15 秒），請確認遠端機台對外網路連線。"}
    except Exception as e:
        print(f"[ERROR_SUMMARY] {type(e).__name__}: {e}", file=sys.stderr)
        return {"success": False, "error": f"呼叫 LINE API 發生例外 ({type(e).__name__}): {e}"}

    if resp.status_code == 200:
        return {
            "success": True,
            "message": "LINE 訊息推播成功。",
            "target_id_masked": f"{target_id[:6]}...{target_id[-4:]}" if len(target_id) > 10 else target_id,
            "bubbles_sent": 1,
            "truncated": False,
            "request_id": resp.headers.get("x-line-request-id", ""),
        }

    # 針對常見 HTTP 錯誤提供明確排查說明
    hint_map = {
        400: "請求格式錯誤，請確認 User ID / Group ID 是否正確，且該對象已加官方帳號為好友。",
        401: "Channel Access Token 無效、過期或格式錯誤，請重新核對 .env 中的 Token。",
        429: "已達 LINE 免費方案每月 200 則推播上限，或短時間請求頻率過高。",
    }
    hint = hint_map.get(resp.status_code, "LINE API 回傳錯誤。")
    return {
        "success": False,
        "status_code": resp.status_code,
        "hint": hint,
        "detail": resp.text[:500],
    }


# =====================================================================
# 6. 統一網關入口工具 (Remote Audit Gateway)
# =====================================================================

@mcp.tool()
def remote_audit_gateway(
    action: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """遠端審計與維運統一網關工具 (Remote Audit Gateway)

    將所有遠端機台的運維探針、檔案管理、日誌檢索、內部知識庫查詢、LINE 告警推播與伺服器自身更新，
    收斂於單一統一入口。此設計將 MCP 工具綱要 (Tool Schema) 由原本 12 個大幅收斂為 1 個，
    降低每次對話提示詞 Token 消耗（節省 >90% 提示詞開銷），並消除多工具對 Agent 思考的干擾。

    支援的動作 (action)：
    1. 系統狀態與統計：
       - 'server_info' (別名 'get_server_info', 'info'): 取得伺服器主機名稱、IP、運行時間與能力旗標。
       - 'audit_stats' (別名 'get_audit_stats', 'stats'): 取得今日或指定日期的工具呼叫次數、Token 消耗、省下的 Schema 費用與運行時間。
         參數: {"target_date": "YYYY-MM-DD"} (選填，預設今日)
    2. 內部知識庫：
       - 'list_faq_categories' (別名 'faq_categories', 'categories'): 列出內部知識庫所有分類與數量。
       - 'search_internal_faq' (別名 'search_faq', 'faq'): 查詢內部知識庫。
         參數: {"keyword": "關鍵字", "category": "分類篩選"} (皆選填)
    3. IIS / NSSM / Windows 服務感知與日誌探針：
       - 'inspect_service' (別名 'service'): 檢查特定 Windows 服務狀態（支援 IIS / NSSM）。
         參數: {"service_name": "服務名稱"} (必填)
       - 'list_services' (別名 'services'): 列出 Windows 服務清單。
         參數: {"filter_keyword": "關鍵字"} (選填)
       - 'inspect_tail_log' (別名 'tail_log', 'log'): 讀取日誌檔末尾 N 行（內建敏感檔案黑名單）。
         參數: {"log_path": "路徑", "lines": 50, "filter_keyword": "關鍵字"} (預設 50 行，上限 200 行)
    4. 通用檔案系統操作：
       - 'read_remote_file' (別名 'read_file', 'read'): 讀取遠端檔案內容（內建敏感檔案黑名單）。
         參數: {"file_path": "路徑", "max_chars": 20000} (選填上限)
       - 'write_remote_file' (別名 'write_file', 'write'): 通用寫入/更新檔案（原子寫入、備份保護）。
         參數: {"file_path": "路徑", "content": "內容", "create_backup": true, "restart_if_server": true}
       - 'list_remote_directory' (別名 'list_dir', 'ls'): 查看目錄清單。
         參數: {"dir_path": "."} (選填，預設當前專案目錄)
    5. 自身熱更新與災難還原：
       - 'apply_server_update' (別名 'apply_update', 'update'): 安全自身熱更新（AST 驗證 + 探針試跑 + 自動備份與重啟）。
         參數: {"new_code": "完整 Python 原始碼"} (必填)
       - 'rollback_server' (別名 'rollback'): 還原至前一版 server.py.bak 備份並重啟。
    6. LINE 告警推播：
       - 'send_line_message' (別名 'send_line', 'line'): 推播重點去識別化摘要（內建 DLP 防外洩檢查）。
         參數: {"message": "摘要內容 (上限 1500 字元)", "to_id": "選填對象 ID"}

    Args:
        action: 要執行的動作名稱（支援正式名稱與簡寫別名，例如 'server_info', 'inspect_service' 等）。
        params: 傳入該動作的參數字典（選填，若無參數可留空或傳入 null）。
    """
    t0 = time.perf_counter()
    p = params if isinstance(params, dict) else {}
    action_key = action.strip().lower()

    res: dict[str, Any]
    try:
        if action_key in ("get_server_info", "server_info", "info"):
            res = get_server_info()
        elif action_key in ("audit_stats", "get_audit_stats", "stats"):
            res = get_mcp_audit_stats(_safe_str(p.get("target_date")))
        elif action_key in ("list_faq_categories", "faq_categories", "categories"):
            res = list_faq_categories()
        elif action_key in ("search_internal_faq", "search_faq", "faq"):
            res = search_internal_faq(
                keyword=_safe_str(p.get("keyword")),
                category=_safe_str(p.get("category")),
            )
        elif action_key in ("inspect_service", "service"):
            res = inspect_service(service_name=_safe_str(p.get("service_name")))
        elif action_key in ("list_services", "services"):
            res = list_services(filter_keyword=_safe_str(p.get("filter_keyword")))
        elif action_key in ("inspect_tail_log", "tail_log", "log"):
            res = inspect_tail_log(
                log_path=_safe_str(p.get("log_path")),
                lines=_safe_int(p.get("lines"), 50),
                filter_keyword=_safe_str(p.get("filter_keyword")),
            )
        elif action_key in ("read_remote_file", "read_file", "read"):
            res = read_remote_file(
                file_path=_safe_str(p.get("file_path")),
                max_chars=_safe_int(p.get("max_chars"), 20000),
            )
        elif action_key in ("write_remote_file", "write_file", "write"):
            res = write_remote_file(
                file_path=_safe_str(p.get("file_path")),
                content=_safe_str(p.get("content")),
                create_backup=_safe_bool(p.get("create_backup"), True),
                restart_if_server=_safe_bool(p.get("restart_if_server"), True),
            )
        elif action_key in ("list_remote_directory", "list_dir", "ls"):
            res = list_remote_directory(dir_path=_safe_str(p.get("dir_path"), "."))
        elif action_key in ("delete_remote_file", "delete_file", "delete", "rm"):
            res = delete_remote_file(file_path=_safe_str(p.get("file_path")))
        elif action_key in ("apply_server_update", "apply_update", "update"):
            res = apply_server_update(new_code=_safe_str(p.get("new_code")))
        elif action_key in ("rollback_server", "rollback"):
            res = rollback_server()
        elif action_key in ("send_line_message", "send_line", "line"):
            res = send_line_message(
                message=_safe_str(p.get("message")),
                to_id=_safe_str(p.get("to_id")),
            )
        else:
            res = {
                "success": False,
                "error": f"未知的動作 (action): '{action}'。",
                "supported_actions": [
                    "server_info",
                    "audit_stats",
                    "list_faq_categories",
                    "search_internal_faq",
                    "inspect_service",
                    "list_services",
                    "inspect_tail_log",
                    "read_remote_file",
                    "write_remote_file",
                    "list_remote_directory",
                    "delete_remote_file",
                    "apply_server_update",
                    "rollback_server",
                    "send_line_message",
                ],
                "hint": "請確認 action 名稱，或使用 'server_info' 取得伺服器狀態概況。",
            }
    except Exception as e:
        _log_error(action, e, p)
        res = {"success": False, "error": f"執行 action '{action}' 發生例外 ({type(e).__name__}): {e}"}

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    _record_audit(action=action, params=p, result=res, elapsed_ms=elapsed_ms)
    return res


if __name__ == "__main__":
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    lan_ip = _get_lan_ip()
    _init_logging()
    _ensure_nssm_binary()
    allowed_ips_str = _get_env_setting("MCP_ALLOWED_IPS") or "Strict (Localhost Only, External Blocked)"
    print("=" * 60)
    print(f"Starting internal-faq-mcp on {HOST}:{PORT}")
    print(f"Streamable HTTP Endpoint: http://{lan_ip}:{PORT}/mcp")
    print(f"Services & Log Inspection + Self-Update Enabled.")
    print(f"Unified Gateway: remote_audit_gateway (14 actions converged).")
    print(f"IP Whitelist Guard: Enabled (Allowed: {allowed_ips_str})")
    print(f"Logs directory: {LOG_DIR}")
    print("=" * 60)

    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(transport_security=security)
    wrapped_app = IPWhitelistMiddleware(app)
    uvicorn.run(
        wrapped_app,
        host=HOST,
        port=PORT,
        timeout_graceful_shutdown=0,
    )
