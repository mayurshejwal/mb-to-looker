"""BigQuery profiling + query-execution tools for the LookML pipeline.

Fixes retained: H (lazy client), I (tabledata.list, no scan), J (identifier
sanitization), E (dataset fallback), C (run_bq_sql target fingerprint).

Added: multi-project dataset resolution. Each table's Metabase `schema` maps to
a {project, dataset} via the user-confirmed `dataset_map` in session state (set
by dataset_tools.confirm_dataset_mapping). Resolution priority for every call:
    explicit project/dataset arg  >  dataset_map[schema]  >  BQ_PROJECT/BQ_DATASET env
"""
from __future__ import annotations
import os
import re
import json
from typing import Optional, Any

from google.api_core.exceptions import GoogleAPIError

from .validation import _fingerprint  # shared SOURCE/TARGET fingerprint

DEFAULT_PROJECT = os.environ.get("BQ_PROJECT", "")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "")

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")          # dataset / table
_PROJECT_RE = re.compile(r"^[A-Za-z0-9\-]+$")        # GCP project ids allow hyphens

_client = None


def _get_client(project: Optional[str] = None):
    """Lazy client (fix H). A project-specific client is made when needed so
    multi-project migrations address the right billing/data project."""
    global _client
    from google.cloud import bigquery  # lazy import
    if project:
        return bigquery.Client(project=project)
    if _client is None:
        _client = bigquery.Client()
    return _client


def _safe_ident(value: str, kind: str) -> str:
    if not value or not _IDENT_RE.match(value):
        raise ValueError(f"Invalid {kind} identifier: {value!r}")
    return value


def _safe_project(value: str) -> str:
    if not value or not _PROJECT_RE.match(value):
        raise ValueError(f"Invalid project identifier: {value!r}")
    return value


def _resolve_location(dataset_id: str, project: str, schema: str,
                      tool_context: Any) -> tuple[str, str]:
    """Return (project, dataset), resolving from args, then dataset_map, then env."""
    dmap = {}
    default_project = ""
    if tool_context is not None:
        try:
            dmap = tool_context.state.get("dataset_map", {}) or {}
            default_project = tool_context.state.get("dataset_default_project", "") or ""
        except Exception:  # noqa: BLE001 - state may be unavailable in some runners
            dmap, default_project = {}, ""

    mapped = dmap.get(schema) if schema else None

    proj = (project
            or (mapped or {}).get("project")
            or default_project
            or DEFAULT_PROJECT)
    ds = (dataset_id
          or (mapped or {}).get("dataset")
          or DEFAULT_DATASET)

    if not ds:
        raise ValueError(
            f"No dataset resolved for schema={schema!r}. Confirm the dataset "
            f"mapping (confirm_dataset_mapping) or pass dataset_id / set BQ_DATASET.")
    ds = _safe_ident(ds, "dataset")
    proj = _safe_project(proj) if proj else ""
    return proj, ds


def get_bq_schema(table_name: str, dataset_id: str = "", project: str = "",
                  mb_schema: str = "", tool_context: Any = None) -> dict:
    """Exact BigQuery column data types for one table.

    dataset_id/project optional; resolved from the confirmed dataset_map using
    `mb_schema` (the table's Metabase schema) when not passed explicitly.
    """
    try:
        proj, ds = _resolve_location(dataset_id, project, mb_schema, tool_context)
        tbl = _safe_ident(table_name, "table")
        client = _get_client(proj or None)
    except (ValueError, GoogleAPIError) as e:
        return {"table": table_name, "status": "error", "message": str(e)}

    project_id = proj or client.project
    query = f"""
        SELECT column_name, data_type
        FROM `{project_id}.{ds}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = @table_name
    """
    try:
        from google.cloud import bigquery
        cfg = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("table_name", "STRING", tbl)])
        job = client.query(query, job_config=cfg)
        results = [{"column": r["column_name"], "type": r["data_type"]} for r in job]
        return {"table": tbl, "project": project_id, "dataset": ds,
                "status": "success", "schema": results}
    except GoogleAPIError as e:
        return {"table": tbl, "status": "error", "message": str(e)}


def get_bq_sample(table_name: str, dataset_id: str = "", project: str = "",
                  mb_schema: str = "", tool_context: Any = None) -> dict:
    """3-row sample WITHOUT scanning the table (tabledata.list, fix I)."""
    try:
        proj, ds = _resolve_location(dataset_id, project, mb_schema, tool_context)
        tbl = _safe_ident(table_name, "table")
        client = _get_client(proj or None)
    except (ValueError, GoogleAPIError) as e:
        return {"table": table_name, "status": "error", "message": str(e)}

    try:
        ds_ref = client.dataset(ds, project=proj or None)
        table_ref = ds_ref.table(tbl)
        rows_iter = client.list_rows(table_ref, max_results=3)
        results = [dict(row.items()) for row in rows_iter]
        clean = json.loads(json.dumps(results, default=str))
        return {"table": tbl, "project": proj or client.project, "dataset": ds,
                "status": "success", "sample_data": clean}
    except GoogleAPIError as e:
        return {"table": tbl, "status": "error", "message": str(e)}


def run_bq_sql(sql: str, project: str = "", row_cap: int = 2000,
               tool_context: Any = None) -> dict:
    """Execute translated SQL and return a fingerprint (TARGET side, fix C).

    For multi-project SQL, fully qualify tables in the SQL itself
    (`project.dataset.table`). `project` here only sets the billing/job project.
    """
    try:
        proj = _safe_project(project) if project else (DEFAULT_PROJECT or "")
        client = _get_client(proj or None)
    except (ValueError, GoogleAPIError) as e:
        return {"status": "error", "message": str(e)}
    try:
        job = client.query(sql)
        rows = [dict(r.items()) for r in job.result(max_results=row_cap)]
        rows = json.loads(json.dumps(rows, default=str))
        fp = _fingerprint(rows)
        fp["status"] = "success"
        return fp
    except GoogleAPIError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": str(e)}
