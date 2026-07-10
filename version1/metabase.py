"""Deterministic Metabase extraction tools.

Plain functions exposed to the ExtractionAgent as FunctionTools. No LLM
reasoning here — pulling metadata is a solved problem, so we keep it out of
the model's token budget and return structured data.

Fixes applied:
  M  list_dashboards / list_databases tolerate BOTH response shapes Metabase
     uses across versions: a bare list [...] and a paginated {"data": [...],
     "total": N} envelope. Previously a wrapped dashboard response would be
     silently truncated to zero.
  D  single auth scheme (X-Metabase-Session), shared with validation.py.
"""
from __future__ import annotations
import os
from typing import Any
import requests

MB_URL = os.environ.get("METABASE_URL", "http://localhost:3000")
MB_SESSION_ID = os.environ.get("METABASE_SESSION_ID", "")


def _headers() -> dict:
    return {"X-Metabase-Session": MB_SESSION_ID, "Content-Type": "application/json"}


def _get(path: str) -> Any:
    r = requests.get(f"{MB_URL}/api{path}", headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _as_list(payload: Any) -> list:
    """Normalize Metabase list responses (fix M).

    Handles: bare list, {"data": [...]}, and paginated {"data": [...], "total": N}.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return payload["data"]
    return []


def list_databases() -> dict:
    """List all databases known to Metabase. Returns {databases: [...]}."""
    dbs = _as_list(_get("/database"))
    return {"databases": [{"id": d["id"], "name": d["name"], "engine": d.get("engine")}
                          for d in dbs]}


def get_database_schema(database_id: int) -> dict:
    """Full table+field metadata for one database. Use for LookML view gen."""
    meta = _get(f"/database/{database_id}/metadata")
    tables = []
    for t in meta.get("tables", []):
        tables.append({
            "id": t["id"], "name": t["name"], "schema": t.get("schema"),
            "fields": [{"id": f["id"], "name": f["name"],
                        "display_name": f.get("display_name"),
                        "base_type": f.get("base_type"),
                        "semantic_type": f.get("semantic_type"),
                        "fk_target_field_id": f.get("fk_target_field_id")}
                       for f in t.get("fields", [])],
        })
    return {"database_id": database_id, "tables": tables}


def list_dashboards() -> dict:
    """List every dashboard id+name. Cheap; drives the migration loop."""
    data = _as_list(_get("/dashboard"))
    return {"dashboards": [{"id": d["id"], "name": d["name"]} for d in data]}


def get_dashboard(dashboard_id: int) -> dict:
    """Full dashboard: parameters + dashcards with positions and card refs."""
    d = _get(f"/dashboard/{dashboard_id}")
    cards = []
    for dc in d.get("dashcards", d.get("ordered_cards", [])):
        if not dc.get("card_id"):
            continue  # text/heading cards
        cards.append({
            "card_id": dc["card_id"], "row": dc["row"], "col": dc["col"],
            "size_x": dc["size_x"], "size_y": dc["size_y"],
            "param_mappings": dc.get("parameter_mappings", []),
        })
    return {"id": d["id"], "name": d["name"],
            "parameters": d.get("parameters", []), "cards": cards}


def get_card(card_id: int) -> dict:
    """One Metabase question: its query (native SQL or MBQL) + viz settings."""
    c = _get(f"/card/{card_id}")
    dq = c.get("dataset_query", {})
    qtype = dq.get("type", "query")
    return {
        "id": c["id"], "name": c["name"], "query_type": qtype,
        "native_sql": dq.get("native", {}).get("query") if qtype == "native" else None,
        "mbql": dq.get("query") if qtype == "query" else None,
        "source_table_id": (dq.get("query", {}) or {}).get("source-table"),
        "database_id": dq.get("database"),
        "viz_type": c.get("display", "table"),
        "viz_settings": c.get("visualization_settings", {}),
    }
