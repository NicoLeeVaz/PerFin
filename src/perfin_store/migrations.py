"""Schema version checks and migration scaffolding.

contract_meta.schema_version records the Access schema version (equal to the contract version
it implements, 1.0.0). Policy, from docs/contracts.md section 6:

* a newer major version is refused (no override);
* a newer minor version is refused too (fail closed: this code cannot know the new fields);
* an older version is upgraded only through an explicit chain in MIGRATIONS, and only when
  the caller asks; there are no migrations yet, so any older version is refused.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import SCHEMA_VERSION, sqlbuild

SUPPORTED = tuple(int(x) for x in SCHEMA_VERSION.split("."))

# from_version -> (to_version, [DDL statements]) ; applied in order by migrate().
MIGRATIONS: Dict[str, Tuple[str, List[str]]] = {}


class SchemaVersionError(RuntimeError):
    pass


def parse_version(text: Optional[str]) -> Tuple[int, int, int]:
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", text or "")
    if not m:
        raise SchemaVersionError("contract_meta.schema_version is missing or malformed")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def read_meta(adapter) -> Dict[str, str]:
    sql, params = sqlbuild.select("contract_meta", ["meta_key", "meta_value"])
    return {k: v for k, v in adapter.query(sql, params)}


def check_version(found: str, supported: Tuple[int, int, int] = SUPPORTED) -> str:
    """Return 'current' or 'older'; raise SchemaVersionError for anything not openable."""
    v = parse_version(found)
    if v[0] > supported[0]:
        raise SchemaVersionError("database schema %s has a newer major version than this PerFin (%d.x); "
                                 "refusing to open it" % (found, supported[0]))
    if v[0] < supported[0]:
        raise SchemaVersionError("database schema %s is an older major version; no migration path" % found)
    if v[1] > supported[1]:
        raise SchemaVersionError("database schema %s is a newer minor version than %d.%d; refusing (fail closed)"
                                 % (found, supported[0], supported[1]))
    return "current" if v[:2] == supported[:2] else "older"


def ensure_compatible(adapter, *, migrate: bool = False,
                      contract_major: Optional[int] = None,
                      contract_minor: Optional[int] = None) -> Dict[str, str]:
    meta = read_meta(adapter)
    state = check_version(meta.get("schema_version"))
    cv = meta.get("contract_version")
    if contract_major is not None and parse_version(cv)[0] != contract_major:
        raise SchemaVersionError("database contract_version %s does not match contract major %d" % (cv, contract_major))
    if contract_minor is not None and parse_version(cv)[1] > contract_minor:
        raise SchemaVersionError("database contract_version %s has a newer minor version than this PerFin; "
                                 "refusing (fail closed)" % cv)
    if state == "older":
        if not migrate:
            raise SchemaVersionError("database schema %s is older; run migrations explicitly" % meta["schema_version"])
        meta = migrate_to_current(adapter, meta)
    return meta


def migrate_to_current(adapter, meta: Dict[str, str]) -> Dict[str, str]:
    version = meta["schema_version"]
    while version != SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise SchemaVersionError("no migration from schema %s to %s" % (version, SCHEMA_VERSION))
        target, statements = MIGRATIONS[version]
        for stmt in statements:
            adapter.execute_ddl(stmt)
        adapter.begin()
        try:
            sql, params = sqlbuild.update("contract_meta", {"meta_value": target}, {"meta_key": "schema_version"})
            adapter.execute(sql, params)
            adapter.commit()
        except Exception:
            adapter.rollback()
            raise
        version = target
    return read_meta(adapter)
