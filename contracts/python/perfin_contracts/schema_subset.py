"""Minimal validator for the JSON Schema keyword subset used by contracts/schemas.

Unknown keywords raise SchemaError, so schemas cannot silently rely on features this
validator does not enforce. Booleans are never accepted as integers. There is no
'number' type: money is integer minor units and rates are decimal strings.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "schemas")
if not os.path.isdir(SCHEMA_DIR):
    from perfin_resources import root as resource_root
    SCHEMA_DIR = str(resource_root() / "contracts" / "schemas")
ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment", "$defs"}
SUPPORTED = ANNOTATIONS | {"$ref", "type", "properties", "required", "additionalProperties", "items", "enum", "const",
                           "pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems",
                           "uniqueItems", "format", "minProperties"}
Error = Tuple[str, str, str]  # (code, json path, message)


class SchemaError(Exception):
    pass


_cache: Dict[str, Any] = {}


def load_schema(name: str) -> Any:
    if name not in _cache:
        with open(os.path.join(SCHEMA_DIR, name), encoding="utf-8") as f:
            _cache[name] = json.load(f)
    return _cache[name]


def _resolve(ref: str, base: str):
    file, _, pointer = ref.partition("#")
    file = file or base
    node = load_schema(file)
    for part in [p for p in pointer.split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node, file


def _type_ok(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "null":
        return value is None
    raise SchemaError(f"unsupported type {t!r}")


def _format_ok(value: str, fmt: str) -> bool:
    if fmt == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return False
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    if fmt == "date-time-utc":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
            return False
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            return True
        except ValueError:
            return False
    raise SchemaError(f"unsupported format {fmt!r}")


def validate(value: Any, schema: Any, base: str, path: str = "$") -> List[Error]:
    errs: List[Error] = []
    unknown = set(schema) - SUPPORTED
    if unknown:
        raise SchemaError(f"{base}: unsupported keywords {sorted(unknown)} at {path}")
    if "$ref" in schema:
        target, file = _resolve(schema["$ref"], base)
        errs += validate(value, target, file, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            code = "E_AMOUNT_NOT_INTEGER" if "integer" in types and isinstance(value, (float, str)) and path.endswith("_minor") else "E_TYPE"
            return errs + [(code, path, f"expected {types}, got {type(value).__name__}")]
    if "const" in schema and value != schema["const"]:
        errs.append(("E_ENUM", path, f"expected {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        errs.append(("E_ENUM", path, f"{value!r} not in {schema['enum']}"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"] or "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(("E_LENGTH", path, "length out of range"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            code = "E_DATE_INVALID" if schema.get("format") in ("date", "date-time-utc") else "E_PATTERN"
            errs.append((code, path, f"{value!r} does not match {schema['pattern']}"))
        elif "format" in schema and not _format_ok(value, schema["format"]):
            errs.append(("E_DATE_INVALID", path, f"{value!r} is not a valid {schema['format']}"))
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
            errs.append(("E_RANGE", path, f"{value} out of range"))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(("E_REQUIRED", f"{path}.{k}", "required field missing"))
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(("E_UNKNOWN_FIELD", f"{path}.{k}", "field not in contract"))
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errs.append(("E_REQUIRED", path, "object needs more properties"))
        for k, sub in props.items():
            if k in value:
                errs += validate(value[k], sub, base, f"{path}.{k}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"] or "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(("E_LENGTH", path, "item count out of range"))
        if schema.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(seen) != len(set(seen)):
                errs.append(("E_DUPLICATE_ID", path, "items must be unique"))
        if "items" in schema:
            for i, v in enumerate(value):
                errs += validate(v, schema["items"], base, f"{path}[{i}]")
    return errs


def check_schema_keywords(schema: Any, where: str = "") -> None:
    """Raise SchemaError if any (nested) schema uses an unsupported keyword."""
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k in ("properties", "$defs"):
                for name, sub in v.items():
                    check_schema_keywords(sub, f"{where}/{k}/{name}")
            elif k == "items":
                check_schema_keywords(v, f"{where}/items")
            elif k not in SUPPORTED:
                raise SchemaError(f"unsupported keyword {k!r} at {where}")
