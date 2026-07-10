"""Model-response callbacks for resilience.

MALFORMED_FUNCTION_CALL is a Gemini *finish reason*: the model tried to emit a
tool call but produced output the API couldn't parse (bad JSON, truncation,
percent/brace-heavy string args). It is NOT an exception, so retry_config
(which retries transient HTTP errors) does not catch it, and after_model_callback
cannot re-invoke the model within the same turn.

What this callback CAN do — and does:
  1. Detect the malformed finish reason.
  2. Log it visibly (so it's not silent noise in the trace).
  3. Replace the empty/dead model response with a short corrective TEXT response.
     On the next turn the model sees that instruction and re-attempts the call,
     usually succeeding because the guidance ("one small call, plain values")
     steers it away from the malformation. Paired with the existing
     core_migration_loop / validation retry, this yields practical self-heal.
"""
from __future__ import annotations
import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger("mb2looker")

_MALFORMED = "MALFORMED_FUNCTION_CALL"


def _finish_reason_str(resp: LlmResponse) -> str:
    fr = getattr(resp, "finish_reason", None)
    if fr is None:
        return ""
    # Gemini gives an enum with .value; LiteLLM gives a plain string.
    return getattr(fr, "value", str(fr))


def malformed_call_recovery(callback_context: CallbackContext,
                            llm_response: LlmResponse) -> LlmResponse | None:
    """after_model_callback: recover from MALFORMED_FUNCTION_CALL.

    Returns a corrective LlmResponse when the model malformed a tool call;
    otherwise returns None so ADK proceeds normally.
    """
    reason = _finish_reason_str(llm_response)
    # Also treat an empty response (no content, no parts) after a tool phase as
    # a soft malformation — same recovery nudge helps.
    has_content = bool(getattr(llm_response, "content", None)
                       and getattr(llm_response.content, "parts", None))

    if _MALFORMED in reason or (not has_content and not reason):
        agent_name = getattr(callback_context, "agent_name", "?")
        logger.warning("MALFORMED_FUNCTION_CALL detected in %s (finish_reason=%r); "
                       "injecting corrective retry nudge.", agent_name, reason)
        return LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part(text=(
                "Your previous tool call could not be parsed "
                "(MALFORMED_FUNCTION_CALL). Retry it now as a SINGLE, SIMPLE "
                "call: one table/view per call, plain scalar argument values, "
                "no embedded Liquid or template syntax in arguments (set "
                "add_date_grouping: true instead of writing Liquid yourself), "
                "and valid minimal JSON. If the argument list was large, split "
                "it into smaller calls."))]))
    return None
