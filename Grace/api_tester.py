"""API Contract & Smart Mock Testing Module for Grace MCP Suite.

提供 OpenAPI / Swagger 規格解析、智慧擬真與邊界值測資生成，以及合規契約檢驗能力。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_SPEC_FILE = Path(__file__).resolve().parent / "sample_api_spec.json"


def load_spec(spec_path: str = "") -> dict[str, Any]:
    """載入 OpenAPI 規格檔案。"""
    target = Path(spec_path) if spec_path else DEFAULT_SPEC_FILE
    if not target.exists():
        raise FileNotFoundError(f"找不到 API 規格檔: {target}")
    with target.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_available_endpoints(spec_path: str = "") -> dict[str, Any]:
    """解析並列出 API 規格中所有可用的 Endpoints 與 Schema 定義。"""
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        return {"success": False, "error": str(e)}

    endpoints = []
    for path, methods in spec.get("paths", {}).items():
        for method, details in methods.items():
            req_body_schema = ""
            try:
                ref = details["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                req_body_schema = ref.split("/")[-1]
            except (KeyError, TypeError):
                pass

            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": details.get("summary", ""),
                "description": details.get("description", ""),
                "request_schema": req_body_schema,
            })

    schemas = list(spec.get("components", {}).get("schemas", {}).keys())
    return {
        "success": True,
        "spec_title": spec.get("info", {}).get("title", "OpenAPI"),
        "total_endpoints": len(endpoints),
        "endpoints": endpoints,
        "available_schemas": schemas,
    }


def generate_mock_payload(schema_name: str, scenario: str = "normal", spec_path: str = "") -> dict[str, Any]:
    """依據指定 Schema 與情境生成智慧測資。

    Args:
        schema_name: 目標結構名稱 (如 'CreateFindingRequest' 或 'ReimbursementRequest')。
        scenario: 測資情境，支援 'normal' (正常合格)、'boundary' (邊界極限值) 或 'malicious' (惡意/格式違規)。
        spec_path: 自訂 OpenAPI 規格路徑 (留空則使用內建範例)。
    """
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        return {"success": False, "error": str(e)}

    schemas = spec.get("components", {}).get("schemas", {})
    if schema_name not in schemas:
        return {
            "success": False,
            "error": f"找不到 Schema '{schema_name}'，目前可用清單: {list(schemas.keys())}",
        }

    schema = schemas[schema_name]
    props = schema.get("properties", {})
    scenario = scenario.lower().strip()

    payload = {}

    # 1. 正常資料生成 (Normal)
    if scenario == "normal":
        for field, meta in props.items():
            ftype = meta.get("type", "string")
            if "example" in meta:
                payload[field] = meta["example"]
            elif "enum" in meta:
                payload[field] = meta["enum"][0]
            elif meta.get("format") == "email":
                payload[field] = "grace.chen@company.com"
            elif meta.get("pattern") == "^[0-9]{8}$":
                payload[field] = "12345678"
            elif meta.get("pattern") == "^[A-Z]{2}-[0-9]{8}$":
                payload[field] = "AB-98765432"
            elif ftype in ("number", "integer"):
                min_v = meta.get("minimum", 10)
                payload[field] = min_v * 10
            elif ftype == "string":
                payload[field] = f"合規測試_{field}"

    # 2. 邊界極限值資料生成 (Boundary)
    elif scenario == "boundary":
        for field, meta in props.items():
            ftype = meta.get("type", "string")
            if "enum" in meta:
                payload[field] = meta["enum"][-1]
            elif ftype in ("number", "integer"):
                # 給出極限值或剛好超出邊界的數值
                payload[field] = meta.get("maximum", 999999) + 1 if "maximum" in meta else 0
            elif ftype == "string":
                max_len = meta.get("maxLength", 100)
                # 超長字串
                payload[field] = "A" * (max_len + 20)

    # 3. 惡意或異常注入資料生成 (Malicious / Exploit)
    elif scenario == "malicious":
        for field, meta in props.items():
            ftype = meta.get("type", "string")
            if "pattern" in meta:
                payload[field] = "INVALID_FORMAT_$$$!!!"
            elif meta.get("format") == "email":
                payload[field] = "not-an-email-at-all"
            elif ftype in ("number", "integer"):
                payload[field] = -99999  # 負數攻擊
            elif ftype == "string":
                # 注入攻擊 Payload
                payload[field] = f"'; DROP TABLE audit_projects; -- <script>alert('{field}')</script>"
            elif "enum" in meta:
                payload[field] = "HACKER_INJECTION_ENUM"

    else:
        return {
            "success": False,
            "error": f"不支援的情境 '{scenario}'，請選擇 'normal', 'boundary', 或 'malicious'。",
        }

    return {
        "success": True,
        "schema_name": schema_name,
        "scenario": scenario,
        "generated_payload": payload,
        "description": f"已依據 {scenario} 情境生成測資。",
    }


def validate_contract(schema_name: str, payload: dict[str, Any], spec_path: str = "") -> dict[str, Any]:
    """比對資料物件是否符合 OpenAPI Schema 定義的契約規範。

    檢查維度：
    1. 必填欄位有無缺漏 (required)
    2. 欄位型態是否正確 (type: string, number, integer, boolean)
    3. 限制規範是否滿足 (enum, pattern, min/max, minLength/maxLength)
    """
    try:
        spec = load_spec(spec_path)
    except Exception as e:
        return {"success": False, "error": str(e)}

    schemas = spec.get("components", {}).get("schemas", {})
    if schema_name not in schemas:
        return {"success": False, "error": f"找不到 Schema '{schema_name}'"}

    schema = schemas[schema_name]
    required_fields = schema.get("required", [])
    properties = schema.get("properties", {})

    violations = []

    # 1. 檢查必填欄位
    for req in required_fields:
        if req not in payload or payload[req] is None or payload[req] == "":
            violations.append(f"[FAIL] 缺少必填欄位: '{req}'")

    # 2. 逐欄檢查型態與限制
    for field, val in payload.items():
        if field not in properties:
            continue

        meta = properties[field]
        expected_type = meta.get("type")

        # 型態檢驗
        if expected_type == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
            violations.append(f"[FAIL] 欄位 '{field}' 型態錯誤: 預期 integer，收到 {type(val).__name__} ({val})")
        elif expected_type == "number" and not isinstance(val, (int, float)):
            violations.append(f"[FAIL] 欄位 '{field}' 型態錯誤: 預期 number，收到 {type(val).__name__} ({val})")
        elif expected_type == "string" and not isinstance(val, str):
            violations.append(f"[FAIL] 欄位 '{field}' 型態錯誤: 預期 string，收到 {type(val).__name__} ({val})")

        # 數值大小檢驗
        if isinstance(val, (int, float)):
            if "minimum" in meta and val < meta["minimum"]:
                violations.append(f"[FAIL] 欄位 '{field}' 低於最小值限制 {meta['minimum']} (目前值: {val})")
            if "maximum" in meta and val > meta["maximum"]:
                violations.append(f"[FAIL] 欄位 '{field}' 高於最大值限制 {meta['maximum']} (目前值: {val})")

        # 字串規則檢驗
        if isinstance(val, str):
            if "minLength" in meta and len(val) < meta["minLength"]:
                violations.append(f"[FAIL] 欄位 '{field}' 長度過短: 最少 {meta['minLength']} 字元 (目前: {len(val)})")
            if "maxLength" in meta and len(val) > meta["maxLength"]:
                violations.append(f"[FAIL] 欄位 '{field}' 長度過長: 最多 {meta['maxLength']} 字元 (目前: {len(val)})")
            if "enum" in meta and val not in meta["enum"]:
                violations.append(f"[FAIL] 欄位 '{field}' 違背列舉值: 允許值為 {meta['enum']} (目前值: '{val}')")
            if "pattern" in meta and not re.match(meta["pattern"], val):
                violations.append(f"[FAIL] 欄位 '{field}' 違背格式規則 '{meta['pattern']}' (目前值: '{val}')")
            if meta.get("format") == "email" and "@" not in val:
                violations.append(f"[FAIL] 欄位 '{field}' 非合法 Email 格式 (目前值: '{val}')")

    is_compliant = len(violations) == 0
    status_summary = "[PASS] 完全合規通過！符合 OpenAPI 契約定義。" if is_compliant else f"[WARN] 發現 {len(violations)} 項違規！"

    return {
        "success": True,
        "is_compliant": is_compliant,
        "summary": status_summary,
        "violation_count": len(violations),
        "violations": violations,
        "schema_name": schema_name,
        "tested_payload": payload,
    }
