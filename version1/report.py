"""Migration report persistence (fix O).

The pipeline's stated goal: after up to 5 self-heal iterations, hand the human
a list of what migrated cleanly and what still needs manual work. Previously the
final `review_report` lived only in session state and evaporated when the run
ended. save_review_report writes it to disk as both machine-readable JSON and a
human-readable Markdown summary.
"""
from __future__ import annotations
import os
import json
import datetime
from typing import Any

OUT_DIR = os.environ.get("LOOKER_OUT_DIR", "./mb2looker_output")


def _report_dir() -> str:
    p = os.path.join(OUT_DIR, "reports")
    os.makedirs(p, exist_ok=True)
    return p


def _normalize(report: Any) -> list[dict]:
    """Accept a list of entity dicts, or a single dict, or a JSON string."""
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except json.JSONDecodeError:
            return [{"entity_type": "unknown", "name": "raw",
                     "status": "needs_review", "notes": report}]
    if isinstance(report, dict):
        # if it's a wrapper like {"review_report": [...]}, unwrap
        if isinstance(report.get("review_report"), list):
            return report["review_report"]
        return [report]
    if isinstance(report, list):
        return report
    return [{"entity_type": "unknown", "name": "raw",
             "status": "needs_review", "notes": str(report)}]


def save_review_report(review_report: Any, attempts: int = 0) -> dict:
    """Persist the final review report to disk (JSON + Markdown).

    Returns {"json_path", "md_path", "counts"} so the agent/router can log it.
    """
    entries = _normalize(review_report)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    rdir = _report_dir()
    json_path = os.path.join(rdir, f"migration_report_{ts}.json")
    md_path = os.path.join(rdir, f"migration_report_{ts}.md")

    counts = {"ok": 0, "needs_review": 0, "failed": 0, "other": 0}
    for e in entries:
        status = (e.get("status") or "other").lower()
        if status not in counts:
            status = "other"
        counts[status] += 1

    payload = {"generated_at": ts, "validation_attempts": attempts,
               "counts": counts, "entities": entries}
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    # Markdown summary for the human reviewer.
    lines = [f"# Metabase → Looker Migration Report",
             f"", f"_Generated: {ts} · self-heal attempts: {attempts}_", f"",
             f"**Summary:** {counts.get('ok', 0)} ok · "
             f"{counts.get('needs_review', 0)} need review · "
             f"{counts.get('failed', 0)} failed", f"",
             f"| Entity | Name | Status | Output path | Notes |",
             f"|---|---|---|---|---|"]
    for e in entries:
        lines.append(
            f"| {e.get('entity_type', '')} | {e.get('name', '')} | "
            f"{e.get('status', '')} | {e.get('output_path', '')} | "
            f"{str(e.get('notes', '')).replace(chr(10), ' ')} |")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    return {"json_path": json_path, "md_path": md_path, "counts": counts}
