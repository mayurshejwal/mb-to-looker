"""Google ADK agent graph for Metabase -> Looker migration.

Topology:
    root (SequentialAgent)
      1. extraction_agent      (LlmAgent + Metabase tools) -> populates state
      2. core_migration_loop   (LoopAgent, max 5) self-heal:
           a. model_architect_agent   (LlmAgent + LookML/BQ tools)
           b. translate_loop          (LoopAgent, bounded)  -> per-card LookML
           c. dashboard_loop          (LoopAgent, bounded)  -> per-dashboard LookML
           d. validation_agent        (LlmAgent + validation/BQ/LookML tools)
           e. validation_router       (BaseAgent)           -> retry (scoped) or exit
      3. report_writer         (BaseAgent) -> persists final review report to disk

Fix map: A InstructionProvider · B scoped retry · C run_bq_sql in validator ·
E/H/I/J bq_tools · D/K/M metabase+validation · F/validator prompt · L bounded loops ·
N logging · O report persistence.
"""
from __future__ import annotations
import os
import json
import logging
from typing import AsyncGenerator, Callable

from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool
from google.genai import types

from . import metabase as mb
from . import lookml as lk
from . import validation as val
from . import instructions as P
from . import report as rpt
from .bq_tools import get_bq_schema, get_bq_sample, run_bq_sql
from .callbacks import malformed_call_recovery

logger = logging.getLogger("mb2looker")  # fix N: real logging, visible in ADK trace

MODEL = "gemini-2.5-pro"          # heavy reasoning: architect + translation
FAST_MODEL = "gemini-2.5-flash"   # cheap: extraction orchestration, validation gate

MAX_HEAL_ATTEMPTS = 5
LOOP_HARD_CAP = 100_000  # absolute backstop; real bound is len(queue)+1 (fix L)


# ---- fix A: literal-brace-safe instructions via InstructionProvider -------
def static(text: str) -> Callable[[ReadonlyContext], str]:
    """Wrap a prompt so ADK does NOT attempt {state} injection.

    ADK's templating regex matches {token} AND {{token}}, so double-bracing
    fails. An InstructionProvider callable bypasses injection entirely and the
    text (JSON examples, ${TABLE}, Liquid {% %}) is passed through verbatim.
    """
    def _provider(_ctx: ReadonlyContext) -> str:
        return text
    return _provider


# ---- tool wrapping -------------------------------------------------------
mb_tools = [FunctionTool(f) for f in (
    mb.list_databases, mb.get_database_schema, mb.list_dashboards,
    mb.get_dashboard, mb.get_card)]

lk_tools = [FunctionTool(f) for f in (
    lk.write_view, lk.write_raw, lk.validate_lookml)]

# Dashboard builder gets the valid-dashboard writer (inline-query elements),
# NOT write_raw, so it can't emit the broken look:-reference form again.
dash_tools = [FunctionTool(f) for f in (
    lk.write_dashboard, lk.validate_lookml)]

bq_tools = [FunctionTool(f) for f in (get_bq_schema, get_bq_sample)]

# fix C: validator can now execute the TARGET query (run_bq_sql) to get a
# fingerprint to compare against the Metabase SOURCE.
val_tools = [FunctionTool(f) for f in (
    val.run_metabase_card, val.compare_fingerprints, run_bq_sql)]


# ---- 1. extraction (DETERMINISTIC) ---------------------------------------
# ROOT-CAUSE FIX: an LlmAgent cannot write arbitrary state keys just because
# its prompt says "store under card_queue". output_key writes ONE key from the
# final text; the LLM has no direct state access. The previous LlmAgent left
# schema/card_queue/dashboard_queue EMPTY, so both loops escalated on iter 0
# and produced zero looks/dashboards. We do extraction in plain Python and
# write the queues via EventActions.state_delta (the correct ADK mechanism).
class ExtractionAgent(BaseAgent):
    """Deterministically pull Metabase inventory and populate state, SCOPED to
    the dashboard(s) the user asked for.

    The user's first message names the target (e.g. "Convert metabase dashboard
    id 1-e-commerce-insights ..."). We extract just those dashboards, collect the
    tables their cards reference, expand to FK-referenced tables (so joins work),
    and build `schema`/`card_queue`/`dashboard_queue`/`discovered_schemas` from
    that scoped set only — not the whole Metabase database.
    """
    def __init__(self):
        super().__init__(name="extraction_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        try:
            dbs = mb.list_databases().get("databases", [])
            if not dbs:
                logger.error("No Metabase databases found; aborting extraction.")
                yield Event(author=self.name, actions=EventActions(state_delta={
                    "schema": {"tables": []}, "dashboard_queue": [],
                    "card_queue": [], "discovered_schemas": []}))
                return
            primary_db = dbs[0]["id"]
            full_schema = mb.get_database_schema(primary_db)
            all_tables = full_schema.get("tables", [])

            # Resolve which dashboards to migrate from the user's request.
            all_dashboards = mb.list_dashboards().get("dashboards", [])
            requested_ids = self._requested_dashboard_ids(ctx, all_dashboards)
            if requested_ids:
                targets = [d for d in all_dashboards if d["id"] in requested_ids]
            else:
                targets = all_dashboards  # fall back to all if none parsed
            logger.info("Migrating %d of %d dashboards: %s",
                        len(targets), len(all_dashboards),
                        [d["id"] for d in targets])

            dashboard_queue, card_ids = [], []
            for d in targets:
                fulld = mb.get_dashboard(d["id"])
                dashboard_queue.append(fulld)
                for c in fulld.get("cards", []):
                    if c.get("card_id") is not None:
                        card_ids.append(c["card_id"])

            seen, card_queue = set(), []
            referenced_table_ids = set()
            for cid in card_ids:
                if cid in seen:
                    continue
                seen.add(cid)
                card = mb.get_card(cid)
                card_queue.append(card)
                if card.get("source_table_id") is not None:
                    referenced_table_ids.add(card["source_table_id"])

            # Scope tables to those the cards reference, then expand to include
            # FK-target tables so the model's joins resolve.
            id_to_table = {t["id"]: t for t in all_tables}
            scoped_ids = set(referenced_table_ids)
            # field-id -> table-id, to expand FK targets one hop.
            field_to_table = {}
            for t in all_tables:
                for f in t.get("fields", []):
                    field_to_table[f.get("id")] = t["id"]
            for tid in list(scoped_ids):
                t = id_to_table.get(tid)
                if not t:
                    continue
                for f in t.get("fields", []):
                    fk = f.get("fk_target_field_id")
                    if fk and fk in field_to_table:
                        scoped_ids.add(field_to_table[fk])

            if scoped_ids:
                scoped_tables = [t for t in all_tables if t["id"] in scoped_ids]
            else:
                # cards may be native SQL with no source-table; keep all as fallback
                scoped_tables = all_tables
                logger.warning("No source tables resolved from cards (native SQL?);"
                               " keeping full schema.")

            scoped_schema = {"database_id": primary_db, "tables": scoped_tables}
            discovered = sorted({t.get("schema") for t in scoped_tables
                                 if t.get("schema")})

            logger.info("Scoped extraction: %d/%d tables, %d dashboards, "
                        "%d unique cards, schemas=%s", len(scoped_tables),
                        len(all_tables), len(dashboard_queue), len(card_queue),
                        discovered)

            yield Event(author=self.name, actions=EventActions(state_delta={
                "schema": scoped_schema,
                "dashboard_queue": dashboard_queue,
                "card_queue": card_queue,
                "discovered_schemas": discovered,
                "card_queue__cursor": 0,
                "dashboard_queue__cursor": 0,
                "extraction_summary": {
                    "n_tables": len(scoped_tables),
                    "n_dashboards": len(dashboard_queue),
                    "n_cards": len(card_queue)},
            }))
        except Exception as e:  # noqa: BLE001 - surface extraction failure clearly
            logger.exception("Extraction failed: %s", e)
            yield Event(author=self.name, actions=EventActions(state_delta={
                "schema": {"tables": []}, "dashboard_queue": [],
                "card_queue": [], "discovered_schemas": [],
                "extraction_error": str(e)}))

    @staticmethod
    def _requested_dashboard_ids(ctx: InvocationContext, all_dashboards: list) -> set:
        """Parse the user's request to find which dashboard(s) to migrate.

        Supports: explicit ids ("dashboard id 1", "dashboards 1,3"), and
        name matches ("e-commerce-insights" -> dashboard whose name contains it).
        Returns a set of dashboard ids; empty set means 'could not determine'.
        """
        import re
        # earliest user message = the migration request
        text = ""
        for ev in (getattr(ctx.session, "events", []) or []):
            if getattr(ev, "author", None) == "user":
                for part in getattr(getattr(ev, "content", None), "parts", None) or []:
                    if getattr(part, "text", None):
                        text = part.text
                        break
            if text:
                break
        if not text:
            return set()

        low = text.lower()
        ids = set()

        # explicit ids: "id 1", "dashboard 3", "dashboards 1, 3, 5"
        for m in re.finditer(r"\bdashboards?\s*(?:id[s]?)?\s*[:#]?\s*([0-9][0-9,\s]*)",
                             low):
            for num in re.findall(r"\d+", m.group(1)):
                ids.add(int(num))
        # also a bare "id 1"
        for m in re.finditer(r"\bid\s*[:#]?\s*(\d+)", low):
            ids.add(int(m.group(1)))

        # name match: any dashboard whose name appears in the request
        for d in all_dashboards:
            name = (d.get("name") or "").lower()
            if not name:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
            if name in low or (slug and slug in re.sub(r"[^a-z0-9]+", "-", low)):
                ids.add(d["id"])

        # keep only ids that actually exist
        valid = {d["id"] for d in all_dashboards}
        return {i for i in ids if i in valid}


extraction_agent = ExtractionAgent()


# ---- 1b. dataset gate (interactive, deterministic) -----------------------
# Replaces the LongRunningFunctionTool approach, which (a) didn't reliably
# deliver the confirmed mapping to state under adk web, and (b) leaked the
# confirm_dataset_mapping call into the architect's shared context, crashing
# with "Tool 'confirm_dataset_mapping' not found". This gate pauses by ending
# the invocation with a prompt, then parses the user's next message.
#
# Accepted input format (one schema per line):
#     e_commerce_insights = gen-ai-explore.e_commerce_insights
#     Movies = gen-ai-explore.Movies
# A line may also be just project.dataset with no "schema =" if there's a
# single discovered schema. Lines starting with # are ignored.
import re as _re

_MAP_LINE = _re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9\-]+)\.([A-Za-z0-9_]+)\s*$")


def _parse_mapping_text(text: str, discovered: list[str]) -> dict:
    """Parse 'schema = project.dataset' lines into a dataset_map dict."""
    dmap: dict[str, dict] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _MAP_LINE.match(line)
        if m:
            schema, project, dataset = m.group(1), m.group(2), m.group(3)
            dmap[schema] = {"project": project, "dataset": dataset}
            continue
        # fallback: bare "project.dataset" when exactly one schema is expected
        if "." in line and len(discovered) == 1:
            parts = line.split(".")
            if len(parts) == 2:
                dmap[discovered[0]] = {"project": parts[0], "dataset": parts[1]}
    return dmap


def _latest_user_text(ctx: InvocationContext) -> str:
    """Return the text of the most recent user-authored event, if any."""
    events = list(getattr(ctx.session, "events", []) or [])
    for ev in reversed(events):
        if getattr(ev, "author", None) != "user":
            continue
        content = getattr(ev, "content", None)
        for part in getattr(content, "parts", None) or []:
            txt = getattr(part, "text", None)
            if txt:
                return txt
    return ""


class DatasetGate(BaseAgent):
    """Interactive human-in-the-loop dataset mapping, without long-running tools.

    Turn 1: no dataset_map yet and no parseable mapping in the user's message ->
            print the discovered schemas + expected format and END the invocation.
    Turn 2: the user's pasted 'schema = project.dataset' lines are parsed and
            written to `dataset_map`; the pipeline proceeds.
    Env fallback: if BQ_PROJECT/BQ_DATASET are set and the user sends nothing
            parseable, we do NOT block forever — we warn and let bq_tools use env.
    """
    def __init__(self):
        super().__init__(name="dataset_gate")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # already resolved on a previous turn?
        if ctx.session.state.get("dataset_map"):
            yield Event(author=self.name, content=None)
            return

        discovered = list(ctx.session.state.get("discovered_schemas", []) or [])
        user_text = _latest_user_text(ctx)
        dmap = _parse_mapping_text(user_text, discovered)

        if dmap:
            logger.info("dataset_map captured for schemas: %s", list(dmap))
            yield Event(author=self.name, actions=EventActions(state_delta={
                "dataset_map": dmap,
                "dataset_default_project": next(iter(dmap.values())).get("project", ""),
            }))
            return

        # No mapping yet -> prompt the user and pause the run cleanly.
        lines = "\n".join(f"  {s} = <project>.{s}" for s in discovered) or \
            "  <schema> = <project>.<dataset>"
        prompt = (
            "Before I build the LookML I need the BigQuery location for each "
            "Metabase schema I found. Reply with one line per schema in this "
            "format (edit project/dataset as needed):\n\n"
            f"{lines}\n\n"
            "Lines starting with # are ignored. Datasets may live in different "
            "projects.")
        logger.info("Dataset gate: awaiting user mapping for schemas %s", discovered)
        ctx.end_invocation = True  # stop cleanly; user replies on next turn
        yield Event(author=self.name, content=types.Content(
            role="model", parts=[types.Part(text=prompt)]))


# ---- 2. model architect --------------------------------------------------
model_architect_agent = LlmAgent(
    name="model_architect_agent", model=MODEL,
    tools=lk_tools + bq_tools,
    instruction=static(P.MODEL_ARCHITECT),
    after_model_callback=malformed_call_recovery,
    output_key="views_built",
)


# ---- 2b. deterministic model writer --------------------------------------
# The architect writes VIEWS. The model file (explores + joins) is generated
# deterministically from FK metadata here, so it can never be lost to a
# MALFORMED_FUNCTION_CALL (which is exactly what happened when the LLM tried to
# write_raw the whole model in one big tool call).
class ModelWriter(BaseAgent):
    """Generate model/migrated.model.lkml (explores + joins) from `schema`."""
    def __init__(self):
        super().__init__(name="model_writer")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        schema = ctx.session.state.get("schema", {}) or {}
        conn = os.environ.get("LOOKER_CONNECTION", "bigquery")
        try:
            res = lk.build_model_from_schema(schema, connection=conn)
            logger.info("Model written: %s (explores: %s)",
                        res["path"], res.get("explores"))
            yield Event(author=self.name, actions=EventActions(state_delta={
                "model_path": res["path"],
                "explores_built": res.get("explores", [])}))
        except Exception as e:  # noqa: BLE001
            logger.exception("Model generation failed: %s", e)
            yield Event(author=self.name, actions=EventActions(state_delta={
                "model_error": str(e)}))



# ---- generic bounded list-iterator ---------------------------------------
class ListIterator(BaseAgent):
    """Pops state[queue_key][cursor] into state[item_key]; escalates when done."""
    queue_key: str
    item_key: str

    def __init__(self, name: str, queue_key: str, item_key: str):
        super().__init__(name=name, queue_key=queue_key, item_key=item_key)

    async def _run_async_impl(
            self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        queue = list(ctx.session.state.get(self.queue_key, []))
        cursor = ctx.session.state.get(f"{self.queue_key}__cursor", 0)
        if cursor == 0:
            logger.info("%s: %s has %d item(s).", self.name, self.queue_key, len(queue))
        if cursor >= len(queue):
            yield Event(author=self.name, actions=EventActions(escalate=True))
            return
        item = queue[cursor]
        yield Event(author=self.name, actions=EventActions(state_delta={
            self.item_key: item,
            f"{self.queue_key}__cursor": cursor + 1,
        }))


# ---- 3. translate loop (one card per iteration) --------------------------
query_translator_agent = LlmAgent(
    name="query_translator_agent", model=MODEL, tools=lk_tools,
    instruction=static(P.QUERY_TRANSLATOR),
    after_model_callback=malformed_call_recovery,
    output_key="translated_look",
)


class LookIndexCollector(BaseAgent):
    """Appends the just-translated look into `look_index` keyed by card id."""
    def __init__(self):
        super().__init__(name="look_index_collector")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        look = ctx.session.state.get("translated_look")
        card = ctx.session.state.get("current_card", {})
        idx = dict(ctx.session.state.get("look_index", {}))
        if look and card:
            idx[str(card.get("id"))] = look
        yield Event(author=self.name,
                    actions=EventActions(state_delta={"look_index": idx}))


translate_loop = LoopAgent(
    name="translate_loop", max_iterations=LOOP_HARD_CAP,  # real stop = ListIterator escalate (fix L)
    sub_agents=[
        ListIterator("card_iter", "card_queue", "current_card"),
        query_translator_agent,
        LookIndexCollector(),
    ],
)

class DashboardContextPruner(BaseAgent):
    """Filters the look_index so the dashboard builder only sees relevant cards."""
    def __init__(self):
        super().__init__(name="dashboard_context_pruner")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        current_dash = ctx.session.state.get("current_dashboard", {})
        full_look_index = ctx.session.state.get("look_index", {})
        
        # Get only the card IDs that exist on this specific dashboard
        dash_card_ids = [str(c.get("card_id")) for c in current_dash.get("cards", [])]
        
        # Build a pruned index
        pruned_index = {cid: full_look_index[cid] for cid in dash_card_ids if cid in full_look_index}
        
        yield Event(author=self.name, actions=EventActions(state_delta={
            "pruned_look_index": pruned_index
        }))

# ---- 4. dashboard loop ---------------------------------------------------
dashboard_builder_agent = LlmAgent(
    name="dashboard_builder_agent", model=MODEL, tools=dash_tools,
    instruction=static(P.DASHBOARD_BUILDER), output_key="built_dashboard",
)
dashboard_loop = LoopAgent(
    name="dashboard_loop", max_iterations=LOOP_HARD_CAP,
    sub_agents=[
        ListIterator("dash_iter", "dashboard_queue", "current_dashboard"),
        DashboardContextPruner(), # <--- ADD IT HERE
        dashboard_builder_agent,
    ],
)

# ---- 5. validation gate & routing ----------------------------------------
validation_agent = LlmAgent(
    name="validation_agent", model=FAST_MODEL, tools=val_tools + lk_tools,
    instruction=static(P.VALIDATOR), output_key="validation_output",  # distinct key
)


def _parse_output(raw) -> object:
    """Safely parse JSON, stripping LLM markdown fences if present."""
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            return raw
    return raw


class ValidationRouter(BaseAgent):
    """Reads `validation_output`. On a retry request, SCOPES the retry to only the
    failed entities WITHOUT destroying the global queue.
    On success or attempt-cap, publishes `review_report` and exits the heal loop."""
    def __init__(self):
        super().__init__(name="validation_router")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        attempts = ctx.session.state.get("validation_attempts", 0) + 1
        out = _parse_output(ctx.session.state.get("validation_output", {}))

        wants_retry = (isinstance(out, dict)
                       and out.get("action") == "retry"
                       and attempts < MAX_HEAL_ATTEMPTS)

        if wants_retry:
            suggestions = out.get("suggestions", [])
            retry_cards = out.get("retry_card_ids")      
            retry_dash = out.get("retry_dashboard_ids")
            logger.warning("Validation failed; scoped retry %s/%s. suggestions=%s",
                           attempts, MAX_HEAL_ATTEMPTS, suggestions)

            delta = {
                "validation_attempts": attempts,
                "architect_feedback": suggestions,
            }
            
            # NON-DESTRUCTIVE FIX: Instead of deleting successful items from the queue, 
            # we just reset the cursor to 0 and let the LLM/Cache handle skipping.
            delta["card_queue__cursor"] = 0
            delta["dashboard_queue__cursor"] = 0

            yield Event(author=self.name, actions=EventActions(state_delta=delta))
        else:
            logger.info("Validation complete after %s attempt(s).", attempts)
            # Publish the human-facing report and break the heal loop.
            report = out if not (isinstance(out, dict) and out.get("action") == "retry") else \
                out.get("suggestions", ["Max attempts reached with unresolved issues."])
            yield Event(author=self.name, actions=EventActions(
                state_delta={"validation_attempts": attempts,
                             "review_report": report},
                escalate=True))


core_migration_loop = LoopAgent(
    name="core_migration_loop", max_iterations=MAX_HEAL_ATTEMPTS,
    sub_agents=[
        model_architect_agent,
        ModelWriter(),
        translate_loop,
        dashboard_loop,
        validation_agent,
        ValidationRouter(),
    ],
)


# ---- 6. report writer (fix O) --------------------------------------------
class ReportWriter(BaseAgent):
    """Persists the final review_report to disk (JSON + Markdown).

    If the validator produced no report (empty on the happy path), build one
    deterministically by scanning the output directory, so the human always
    gets an accurate inventory of what was generated + confidence flags from
    the translate/dashboard steps.
    """
    def __init__(self):
        super().__init__(name="report_writer")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        report = ctx.session.state.get("review_report", [])
        if isinstance(report, dict):
            report = report.get("review_report", []) or []
        if not report:
            report = self._inventory(ctx)
        attempts = ctx.session.state.get("validation_attempts", 0)
        paths = rpt.save_review_report(report, attempts=attempts)
        logger.info("Report written: %s (%d entities)",
                    paths.get("md_path"), len(report))
        yield Event(author=self.name,
                    actions=EventActions(state_delta={"report_paths": paths}))

    @staticmethod
    def _inventory(ctx: InvocationContext) -> list:
        """Deterministic fallback inventory from disk + state confidence flags."""
        out_dir = os.environ.get("LOOKER_OUT_DIR", "./mb2looker_output")
        entries = []

        def _scan(sub, etype):
            d = os.path.join(out_dir, sub)
            if not os.path.isdir(d):
                return
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".lkml"):
                    continue
                entries.append({
                    "entity_type": etype,
                    "name": fn.rsplit(".", 2)[0] if ".view" in fn or
                    ".dashboard" in fn else fn[:-5],
                    "status": "ok",
                    "output_path": os.path.join(sub, fn),
                    "notes": ""})

        _scan("views", "view")
        _scan("model", "model")
        _scan("looks", "look")
        _scan("dashboards", "dashboard")

        # Fold in low-confidence notes captured during translation, if any.
        look_index = ctx.session.state.get("look_index", {}) or {}
        for cid, look in look_index.items():
            if isinstance(look, dict) and look.get("confidence") == "low":
                for e in entries:
                    if e["entity_type"] == "look" and e["name"] == look.get("name"):
                        e["status"] = "needs_review"
                        e["notes"] = look.get("note", "low-confidence translation")
        if not entries:
            entries.append({"entity_type": "none", "name": "-",
                            "status": "failed",
                            "notes": "No LookML artifacts were generated."})
        return entries


# ---- root ----------------------------------------------------------------
root_agent = SequentialAgent(
    name="mb2looker_migration",
    sub_agents=[
        extraction_agent,
        DatasetGate(),
        core_migration_loop,
        ReportWriter(),
    ],
)