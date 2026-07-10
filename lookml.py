"""LookML writing + validation tools.

The LLM decides *what* LookML to write. These tools handle the deterministic
parts: serializing a dict spec to .lkml text, writing files, and running lkml
parse validation so the agent gets a compile signal to self-correct against.

Fixes in this version:
  * sql_table_name is auto-backticked when it contains a hyphen (GCP projects
    like `gen-ai-explore` are invalid BigQuery identifiers unquoted in LookML).
  * drill_fields defaults to a richer set when the model gives only [id].
  * dynamic date-grouping generated deterministically (no Liquid in tool args).
"""
from __future__ import annotations
import os
import re
from typing import Optional

OUT_DIR = os.environ.get("LOOKER_OUT_DIR", "./mb2looker_output")

# Keys whose values must be wrapped in double quotes in LookML.
_QUOTED_KEYS = {"label", "description", "group_label", "view_label", "group_item_label"}

# Timeframe options offered by the deterministic date-grouping parameter.
_DATE_GROUP_TIMEFRAMES = ["date", "week", "month", "quarter", "year"]

# A BigQuery FQN is project.dataset.table; if any part has a hyphen (legal in
# GCP project ids) the whole reference must be backtick-quoted in LookML.
_NEEDS_BACKTICKS = re.compile(r"[^A-Za-z0-9_.]")


def _ensure(sub: str) -> str:
    p = os.path.join(OUT_DIR, sub)
    os.makedirs(p, exist_ok=True)
    return p


def _quote_table_ref(ref: str) -> str:
    """Backtick a BigQuery table reference if it isn't already and needs it."""
    r = ref.strip()
    if r.startswith("`") and r.endswith("`"):
        return r
    if _NEEDS_BACKTICKS.search(r):  # hyphen or other special char present
        return f"`{r}`"
    return r


def _fmt_params(d: dict, indent: int) -> str:
    """Serialize a param dict to LookML lines."""
    pad = "  " * indent
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k} {{")
            out.append(_fmt_params(v, indent + 1))
            out.append(f"{pad}}}")
        elif isinstance(v, (list, tuple)):
            out.append(f"{pad}{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, bool):
            out.append(f"{pad}{k}: {'yes' if v else 'no'}")
        elif k in _QUOTED_KEYS:
            out.append(f'{pad}{k}: "{v}"')
        else:
            out.append(f"{pad}{k}: {v}")
    return "\n".join(out)


def _render_date_grouping(base_dimension_group: str) -> str:
    """Deterministically emit the dynamic date-grouping parameter + dimension.

    Generates a date_granularity parameter and a dynamic_date dimension using a
    proper Liquid if/elsif/else/endif chain. The Liquid lives ONLY in this
    Python-generated text, never in a tool-call argument.
    """
    allowed = "\n".join(
        f'      allowed_value: {{ label: "{tf.capitalize()}" value: "{tf}" }}'
        for tf in _DATE_GROUP_TIMEFRAMES)
    branches = []
    for i, tf in enumerate(_DATE_GROUP_TIMEFRAMES):
        kw = "if" if i == 0 else "elsif"
        branches.append(
            f"      {{% {kw} date_granularity._parameter_value == '{tf}' %}}"
            f"${{{base_dimension_group}_{tf}}}")
    branches.append(f"      {{% else %}}${{{base_dimension_group}_month}}")
    branches.append("      {% endif %}")
    whens = "\n".join(branches)
    return (
        "\n  parameter: date_granularity {\n"
        "    type: unquoted\n"
        f"{allowed}\n"
        "    default_value: \"month\"\n"
        "  }\n\n"
        "  dimension: dynamic_date {\n"
        "    label: \"Date (dynamic)\"\n"
        "    sql:\n"
        f"{whens} ;;\n"
        "  }\n"
    )


def write_view(view_name: str, sql_table_name: str,
               dimensions: list[dict], measures: list[dict],
               add_date_grouping: bool = False,
               date_grouping_base: str = "") -> dict:
    """Write a LookML view file.

    sql_table_name is auto-backticked if it contains a hyphen (e.g. a GCP
    project id like gen-ai-explore), which is required for BigQuery refs.
    Time dimensions with 'timeframes' are auto-promoted to dimension_group.
    add_date_grouping appends a deterministic dynamic date parameter+dimension.
    """
    safe_table = _quote_table_ref(sql_table_name)
    lines = [f"view: {view_name} {{",
             f"  sql_table_name: {safe_table} ;;", ""]
    first_time_dim: Optional[str] = None
    for base_kind, items in (("dimension", dimensions), ("measure", measures)):
        for it in items:
            kind = base_kind
            if base_kind == "dimension" and it.get("type") == "time" and "timeframes" in it:
                kind = "dimension_group"
                if first_time_dim is None:
                    first_time_dim = it.get("name")
            name = it.get("name", f"unnamed_{kind}")
            body = {k: v for k, v in it.items() if k != "name"}
            # Enrich thin count drill_fields: [id] -> [id, <first string dim>]
            if (base_kind == "measure" and body.get("type") == "count"
                    and body.get("drill_fields") in ([["id"]], ["id"])):
                str_dims = [d.get("name") for d in dimensions
                            if d.get("type") == "string" and d.get("name")]
                if str_dims:
                    body["drill_fields"] = ["id"] + str_dims[:3]
            if "sql" in body:  # sql needs the ;; terminator
                body["sql"] = f'{body["sql"]} ;;'
            lines.append(f"  {kind}: {name} {{")
            lines.append(_fmt_params(body, 2))
            lines.append("  }")
            lines.append("")

    if add_date_grouping:
        base = date_grouping_base or first_time_dim
        if base:
            lines.append(_render_date_grouping(base))

    lines.append("}")
    path = os.path.join(_ensure("views"), f"{view_name}.view.lkml")
    text = "\n".join(lines)
    with open(path, "w") as f:
        f.write(text)
    return {"path": path, "bytes": len(text)}


def write_raw(rel_path: str, content: str) -> dict:
    """Escape hatch: write arbitrary LookML text (explores, dashboards, looks)."""
    full = os.path.join(OUT_DIR, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return {"path": full, "bytes": len(content)}


def validate_lookml(path: str) -> dict:
    """Parse a .lkml file with the `lkml` library for a compile signal.
    Fails loudly if lkml is not installed. {"ok": bool, "error": str|None}."""
    try:
        import lkml
    except ImportError:
        return {"ok": False,
                "error": "lkml python package is missing. Cannot validate."}
    try:
        with open(path) as f:
            lkml.load(f)
        return {"ok": True, "error": None}
    except Exception as e:  # lkml raises on syntax errors
        return {"ok": False, "error": str(e)}


# ============================================================================
# Deterministic model (explores + joins) and dashboard writers.
# These replace fragile large LLM tool calls (which lost the model file to a
# MALFORMED_FUNCTION_CALL) with reliable code generation from FK metadata.
# ============================================================================

def _view_name_for_table(table_name: str) -> str:
    """LookML view names are lower_snake; mirror how write_view is invoked."""
    return table_name.strip().lower()


def build_model_from_schema(schema: dict, connection: str = "bigquery",
                            model_filename: str = "migrated.model.lkml") -> dict:
    """Deterministically generate the model file: connection, includes, a
    datagroup, and one explore per base table with joins inferred from
    Metabase fk_target_field_id metadata.

    `schema` is the state object from metabase.get_database_schema:
        {"tables": [{"id","name","schema","fields":[{"id","name",
          "semantic_type","fk_target_field_id"}, ...]}, ...]}
    Join inference: a field with fk_target_field_id pointing at another table's
    field becomes a many_to_one left_outer join on that FK.
    """
    tables = schema.get("tables", []) if isinstance(schema, dict) else []

    # Map every field id -> (table_name, field_name) to resolve FK targets.
    field_index: dict = {}
    for t in tables:
        for f in t.get("fields", []):
            if f.get("id") is not None:
                field_index[f["id"]] = (t["name"], f["name"])

    lines = [f"connection: \"{connection}\"", "",
             "include: \"/views/*.view.lkml\"", "",
             "datagroup: default_datagroup {",
             "  sql_trigger: SELECT CURRENT_DATE() ;;",
             "  max_cache_age: \"24 hours\"",
             "}", "",
             "persist_with: default_datagroup", ""]

    for t in tables:
        tname = t["name"]
        vname = _view_name_for_table(tname)
        explore_lines = [f"explore: {vname} {{"]
        seen_joins = set()
        for f in t.get("fields", []):
            fk = f.get("fk_target_field_id")
            if not fk or fk not in field_index:
                continue
            target_table, target_field = field_index[fk]
            tvname = _view_name_for_table(target_table)
            if tvname == vname or tvname in seen_joins:
                continue
            seen_joins.add(tvname)
            src_field = f["name"]
            explore_lines.append(f"  join: {tvname} {{")
            explore_lines.append(
                f"    sql_on: ${{{vname}.{src_field}}} = "
                f"${{{tvname}.{target_field}}} ;;")
            explore_lines.append("    relationship: many_to_one")
            explore_lines.append("    type: left_outer")
            explore_lines.append("  }")
        explore_lines.append("}")
        lines.extend(explore_lines)
        lines.append("")

    text = "\n".join(lines)
    path = os.path.join(_ensure("model"), model_filename)
    with open(path, "w") as f:
        f.write(text)
    return {"path": path, "bytes": len(text),
            "explores": [_view_name_for_table(t["name"]) for t in tables]}


def _fmt_vis_config(vis: dict, indent: int = 4) -> str:
    pad = " " * indent
    out = [f"{pad}vis_config:"]
    for k, v in (vis or {}).items():
        if isinstance(v, dict):
            out.append(f"{pad}  {k}: {{}}" if not v else f"{pad}  {k}:")
            for kk, vv in v.items():
                out.append(f"{pad}    {kk}: {vv}")
        elif isinstance(v, bool):
            out.append(f"{pad}  {k}: {str(v).lower()}")
        elif v == "":
            out.append(f"{pad}  {k}: ''")
        else:
            out.append(f"{pad}  {k}: {v}")
    return "\n".join(out)


def write_dashboard(dashboard_name: str, title: str, elements: list[dict],
                    model: str = "migrated") -> dict:
    """Write a VALID LookML dashboard file with self-contained (inline-query)
    elements. Each element must specify model+explore+fields+type directly;
    we do NOT use `look:` refs (those point at saved Looks in the instance,
    which don't exist for a fresh migration).

    elements: list of dicts like
      {"name","title","explore","fields":[...],"type":"looker_line",
       "sorts":[...],"limit":500,"row":0,"col":0,"width":8,"height":6,
       "vis_config":{...}, "pivots":[...], "filters":{field:value}}
    """
    lines = [f"- dashboard: {dashboard_name}",
             f"  title: {title}",
             "  layout: newspaper",
             "  elements:"]
    for el in elements:
        lines.append(f"  - name: {el['name']}")
        lines.append(f"    title: {el.get('title', el['name'])}")
        lines.append(f"    model: {model}")
        lines.append(f"    explore: {el['explore']}")
        lines.append(f"    type: {el.get('type', 'looker_grid')}")
        fields = el.get("fields", [])
        lines.append(f"    fields: [{', '.join(fields)}]")
        if el.get("pivots"):
            lines.append(f"    pivots: [{', '.join(el['pivots'])}]")
        if el.get("sorts"):
            lines.append(f"    sorts: [{', '.join(el['sorts'])}]")
        if el.get("filters"):
            lines.append("    filters:")
            for fk, fv in el["filters"].items():
                lines.append(f"      {fk}: \"{fv}\"")
        lines.append(f"    limit: {el.get('limit', 500)}")
        lines.append(f"    row: {el.get('row', 0)}")
        lines.append(f"    col: {el.get('col', 0)}")
        lines.append(f"    width: {el.get('width', 8)}")
        lines.append(f"    height: {el.get('height', 6)}")
        if el.get("listen"):
            lines.append("    listen:")
            for lk_name, lk_field in el["listen"].items():
                lines.append(f"      {lk_name}: {lk_field}")
        if el.get("vis_config"):
            lines.append(_fmt_vis_config(el["vis_config"]))
    text = "\n".join(lines) + "\n"
    path = os.path.join(_ensure("dashboards"),
                        f"{dashboard_name}.dashboard.lkml")
    with open(path, "w") as f:
        f.write(text)
    return {"path": path, "bytes": len(text), "element_count": len(elements)}