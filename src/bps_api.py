"""Allowlisted read-only BPS operations generated from the official OpenAPI spec."""
import json
import re
from difflib import get_close_matches
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote, urlencode

_root = files(__package__) if __package__ else Path(__file__).parent
REGISTRY = json.loads(_root.joinpath("bps_operations.json").read_text(encoding="utf-8"))
OPERATIONS = REGISTRY["operations"]


def credential(headers, fallback="", service="bps") -> str:
    """Credentials are request scoped; never persist a visitor's API key."""
    key = headers.get("x-bps-sdgs-token") if service == "sdgs" else None
    if key is None and service != 'sdgs':
        key = headers.get("x-bps-api-key")
    authorization = headers.get("authorization")
    if key is None and authorization is not None:
        if not authorization.lower().startswith("bearer "):
            raise ValueError("Gunakan Authorization: Bearer API_KEY_BPS.")
        key = authorization[7:]
    key = key if key is not None else fallback
    if not key or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{8,512}", key):
        raise ValueError("API key belum tersedia atau format tidak valid. Gunakan header X-BPS-API-Key atau Authorization: Bearer.")
    return key


def catalog(operation="", query="") -> dict:
    if operation:
        if operation not in OPERATIONS:
            names = sorted(OPERATIONS)
            return {'ok': False, 'error': 'unknown_operation', 'message': 'Nama operasi tidak dikenal. Gunakan nama persis dari valid_operations.', 'operation': operation, 'valid_operations': names, 'suggestions': [name for name in names if operation.lower() in name.lower()][:5] or get_close_matches(operation, names, n=3)}
        spec = OPERATIONS[operation]
        return {"ok": True, "operation": operation, **spec, "source": REGISTRY["source"]}
    items = [{"operation": name, "summary": op["summary"], "group": op["group"], "credential": op["credential"]}
             for name, op in OPERATIONS.items()
             if query.lower() in (name + " " + op["summary"] + " " + op["group"]).lower()]
    return {"ok": True, "operations": items, "total": len(items), "source": REGISTRY["source"]}


def build_request(operation: str, parameters: dict, key: str):
    if operation not in OPERATIONS or not isinstance(parameters, dict):
        raise ValueError("Operasi atau parameter tidak valid; gunakan bps_endpoints.")
    spec = OPERATIONS[operation]
    known = {p["name"]: p for p in spec["parameters"]}
    if any(name not in known for name in parameters):
        raise ValueError("Parameter tidak didukung untuk operasi ini.")
    path, query = spec["path"], {}
    for name, param in known.items():
        if name not in parameters:
            if param.get("required"):
                raise ValueError(f"Parameter wajib: {name}")
            continue
        value = parameters[name]
        schema = param.get("schema", {})
        if isinstance(value, bool) or not isinstance(value, (str, int)) or len(str(value)) > 500:
            raise ValueError(f"Parameter tidak valid: {name}")
        if schema.get("type") == "integer" and not isinstance(value, int):
            raise ValueError(f"Parameter harus integer: {name}")
        if schema.get("type") == "string" and not isinstance(value, str):
            raise ValueError(f"Parameter harus string: {name}")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"Pilihan parameter tidak valid: {name}")
        if isinstance(value, int) and (value < schema.get("minimum", value) or value > schema.get("maximum", value)):
            raise ValueError(f"Parameter di luar rentang: {name}")
        if isinstance(value, str) and (len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 500) or (schema.get("pattern") and not re.search(schema["pattern"], value))):
            raise ValueError(f"Format parameter tidak valid: {name}")
        if param["in"] == "path":
            if not str(value) or str(value) in {".", ".."} or re.search(r"[/\\?#%\x00-\x1f]", str(value)):
                raise ValueError(f"Segmen path tidak valid: {name}")
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        else:
            query[name] = str(value)
    if operation == "listDomains" and parameters.get("type") == "kabbyprov" and not parameters.get("prov"):
        raise ValueError("Parameter prov wajib untuk type kabbyprov.")
    public_path = path.replace("{key}", "***")
    path = path.replace("{key}", quote(key, safe=""))
    suffix = "?" + urlencode(query) if query else ""
    return "https://webapi.bps.go.id" + path + suffix, "https://webapi.bps.go.id" + public_path + suffix, ({"Token": key} if spec["credential"] == "sdgs" else {})


def sanitize(value, secrets):
    if isinstance(value, dict):
        return {sanitize(k, secrets): sanitize(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "***").replace(quote(secret, safe=""), "***")
        return re.sub(r"(/key/)[^/?#\s\"<>]+", r"\1***", value)
    return value
