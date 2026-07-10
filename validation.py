"""Parity validation.

We run the *original* Metabase card (SOURCE of truth) and compare a cheap
fingerprint (row count + column set + per-column numeric sums) against the
translated query executed on BigQuery (TARGET, via bq_tools.run_bq_sql).

Fixes applied:
  D  auth unified to the Metabase session header (X-Metabase-Session), matching
     metabase.py. No more x-api-key / MB_API_KEY second scheme.
  K  compare_fingerprints uses relative tolerance on numeric sums (float rounding
     and NULL handling differ between Metabase's source DB and BigQuery) and
     de-duplicates correlated issues so one root cause (e.g. a renamed column)
     doesn't cascade into a hard 'failed'.
"""
from __future__ import annotations
import os
import hashlib
import requests

MB_URL = os.environ.get("METABASE_URL", "http://localhost:3000")
MB_SESSION_ID = os.environ.get("METABASE_SESSION_ID", "")  # fix D: single auth scheme

# Relative tolerance for cross-engine numeric comparison (fix K).
NUM_REL_TOL = float(os.environ.get("VALIDATION_NUM_REL_TOL", "0.01"))  # 1%


def _headers() -> dict:
    return {"X-Metabase-Session": MB_SESSION_ID, "Content-Type": "application/json"}


def run_metabase_card(card_id: int, row_cap: int = 2000) -> dict:
    """Execute a card in Metabase, return a fingerprint of its result set."""
    r = requests.post(f"{MB_URL}/api/card/{card_id}/query/json",
                      headers=_headers(), timeout=120)
    r.raise_for_status()
    rows = r.json()[:row_cap]
    fp = _fingerprint(rows)
    fp["status"] = "success"
    return fp


def _fingerprint(rows: list[dict]) -> dict:
    if not rows:
        return {"row_count": 0, "columns": [], "checksum": "empty", "numeric_sums": {}}
    cols = sorted(rows[0].keys())
    sums: dict[str, float] = {}
    for row in rows:
        for c in cols:
            v = row.get(c)
            if isinstance(v, bool):
                continue  # don't sum booleans as ints
            if isinstance(v, (int, float)):
                sums[c] = sums.get(c, 0.0) + v
    # checksum kept for quick-equality fast path; comparison relies on tolerant sums.
    h = hashlib.sha256(str(sorted(sums.items())).encode()).hexdigest()[:16]
    return {"row_count": len(rows), "columns": cols, "checksum": h,
            "numeric_sums": {k: round(v, 4) for k, v in sums.items()}}


def _sums_within_tolerance(src: dict, tgt: dict) -> list[str]:
    """Return list of columns whose numeric sums differ beyond NUM_REL_TOL (fix K)."""
    drifted = []
    keys = set(src.get("numeric_sums", {})) & set(tgt.get("numeric_sums", {}))
    for k in sorted(keys):
        a = src["numeric_sums"][k]
        b = tgt["numeric_sums"][k]
        scale = max(abs(a), abs(b), 1e-9)
        if abs(a - b) / scale > NUM_REL_TOL:
            drifted.append(k)
    return drifted


def compare_fingerprints(source: dict, target: dict) -> dict:
    """Return a verdict the ValidationAgent turns into ok/needs_review/failed.

    Tolerant + correlated-issue-aware (fix K):
      - row_count mismatch                              -> structural issue
      - column-set mismatch                             -> structural issue
      - numeric drift beyond tolerance on shared cols   -> data issue
    A column-set mismatch usually explains any checksum drift, so we don't
    double-count them. Verdict: ok (0 issues), needs_review (1 issue),
    failed (2+ *independent* issues).
    """
    structural = []
    if source.get("row_count") != target.get("row_count"):
        structural.append(
            f"row_count {source.get('row_count')} != {target.get('row_count')}")
    cols_differ = set(source.get("columns", [])) != set(target.get("columns", []))
    if cols_differ:
        structural.append("column set differs")

    data_issues = []
    if not cols_differ:
        # only compare numbers when columns line up; otherwise it's a correlated symptom
        drifted = _sums_within_tolerance(source, target)
        if drifted:
            data_issues.append(f"numeric drift on: {', '.join(drifted)}")

    issues = structural + data_issues
    n = len(issues)
    verdict = "ok" if n == 0 else ("needs_review" if n == 1 else "failed")
    return {"verdict": verdict, "issues": issues}