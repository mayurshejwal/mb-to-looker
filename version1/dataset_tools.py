"""Human-in-the-loop dataset mapping confirmation.

Metabase knows which schemas its questions reference (each table carries a
`schema` field, which for a BigQuery connection is the dataset name). But two
things Metabase can't always tell us reliably:
  1. whether that schema string EXACTLY matches the BigQuery dataset id, and
  2. the GCP PROJECT the dataset lives in (dashboards may span projects).

So instead of asking the user to type everything from scratch, we AUTO-DISCOVER
a proposed mapping from the extracted schema and ask the user only to CONFIRM or
EDIT it. This is a LongRunningFunctionTool: it returns a `pending` payload and
pauses the run; the client (adk web now, your GUI later) collects the user's
confirmed mapping and resumes the agent by sending a FunctionResponse whose
content becomes `dataset_map` in state.

Resume contract (what the client sends back as the FunctionResponse):
    {
      "status": "confirmed",
      "dataset_map": {
         "<metabase_schema>": {"project": "<gcp_project>", "dataset": "<bq_dataset>"},
         ...
      },
      "default_project": "<gcp_project>"   # optional; used when a mapping omits project
    }
"""
from __future__ import annotations
import os
from typing import Any

from google.adk.tools import LongRunningFunctionTool

DEFAULT_PROJECT = os.environ.get("BQ_PROJECT", "")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "")


def confirm_dataset_mapping(discovered_schemas: list[str]) -> dict[str, Any]:
    """Confirm the Metabase-schema -> BigQuery {project, dataset} mapping.

    Call this ONCE after extraction, passing the list of distinct `schema`
    values found across the extracted tables (state key `schema`.tables[].schema).
    The tool proposes a mapping and PAUSES for the user to confirm or edit it
    (including project, to support multi-project dashboards).

    Args:
        discovered_schemas: distinct Metabase schema names found during extraction.

    Returns:
        A pending payload describing the proposed mapping. The run pauses here;
        the client resumes it with the user's confirmed `dataset_map`.
    """
    # Build a best-guess proposal: schema name doubles as the dataset name,
    # project defaults to BQ_PROJECT/ADC default. User can override any of it.
    proposed = {
        s: {"project": DEFAULT_PROJECT or "<your-gcp-project>",
            "dataset": s or DEFAULT_DATASET or "<dataset>"}
        for s in sorted(set(discovered_schemas or []))
    }
    return {
        "status": "pending_user_confirmation",
        "message": (
            "Confirm the BigQuery project + dataset for each Metabase schema "
            "below. Edit any dataset/project that is wrong, add missing ones, "
            "then confirm. Datasets may live in different projects."),
        "proposed_dataset_map": proposed,
        "default_project": DEFAULT_PROJECT or None,
        "resume_schema": {
            "status": "confirmed",
            "dataset_map": {
                "<metabase_schema>": {"project": "<gcp_project>",
                                      "dataset": "<bq_dataset>"}
            },
            "default_project": "<gcp_project optional>",
        },
    }


# Wrapped for the agent. The LLM calls it; ADK pauses the run until the client
# sends the confirmed FunctionResponse.
confirm_dataset_mapping_tool = LongRunningFunctionTool(func=confirm_dataset_mapping)
