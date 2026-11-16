"""Agent runtime — runs a workspace's AI agents inside the platform.

An agent is just a stored config (system_prompt, greeting, etc.). Running it
means: build messages (system + RAG context + history + user), call the LLM.

Features:
  - Strict grounding rules (no hallucination)
  - Responsible-AI guardrails (screen input/output)
  - Structured tool-calling (book_slot, capture_lead, escalate)
"""
import json
import re

from services.llm_service import llm
from services.guardrails_service import screen_input, screen_output
from services import language_service as lang_svc
from rag.vector_store import vector_store

# ─── Tool-calling ────────────────────────────────────────────────────
SUPPORTED_ACTIONS = {
    "book_slot": {"required": ["time"], "optional": ["name", "email", "service"]},
    "capture_lead": {"required": ["name"], "optional": ["email", "phone", "interest"]},
    "escalate": {"required": ["reason"], "optional": ["priority", "contact"]},
}

TOOL_CALLING_ADDENDUM = """
When the user clearly wants to perform an action, respond with a JSON block:
{"action": "<action_name>", ...params}

Available actions:
- book_slot: Book an appointment. Params: time (required), name, email, service
- capture_lead: Capture contact info. Params: name (required), email, phone, interest
- escalate: Escalate to human. Params: reason (required), priority, contact

Only emit an action JSON when you have enough information. Otherwise ask for details naturally.
"""

REFUSAL_MESSAGE = "I'm sorry, I can't help with that request. Is there something else I can assist you with regarding our business?"


def run_agent(agent_config: dict, business_context: str, user_message: str,
              history: list[dict] | None = None, workspace_id: str | None = None,
              language: dict | str | None = None) -> str:
    """Run the agent. Returns the text reply (may contain a tool-call JSON).

    `language` may be a code, or an already-analysed language dict. It is
    detected from the visitor's own message when not supplied.

    Note this resolves the VISITOR's language, not the business's: a salon whose
    owner configured everything in Hindi can still be messaged in English or
    Tamil by a customer, and the reply should follow the customer.
    """
    history = history or []

    # ── Guardrails: screen input ──
    input_check = screen_input(user_message)
    if not input_check["safe"]:
        return lang_svc.localize(REFUSAL_MESSAGE, lang_svc.info(
            language if isinstance(language, str) else
            (language or {}).get("code") if isinstance(language, dict) else None))

    lang = (language if isinstance(language, dict) and "locale" in language
            else lang_svc.analyze(user_message,
                                  declared=language if isinstance(language, str) else None))

    system_prompt = agent_config.get("system_prompt", "You are a helpful assistant.")

    # RAG: pull relevant business memory for grounding.
    rag_snippets = []
    if workspace_id:
        try:
            rag_snippets = vector_store.query_business_context(
                workspace_id, user_message, n_results=3)
            # The stored context is usually whatever language the business was
            # described in, and the embedder is not reliably cross-lingual. So a
            # question asked in Tamil about an English-described business can
            # retrieve nothing. Querying again with the English gloss and merging
            # recovers those hits, at no extra inference cost since the gloss
            # already exists.
            if lang["code"] != lang_svc.DEFAULT_LANG and lang.get("english"):
                extra = vector_store.query_business_context(
                    workspace_id, lang["english"], n_results=3)
                for snippet in extra:
                    if snippet not in rag_snippets:
                        rag_snippets.append(snippet)
        except Exception:
            rag_snippets = []
    rag_block = ("\n\nRelevant business info:\n" + "\n".join(rag_snippets)) if rag_snippets else ""

    # Determine if this agent has tool-calling enabled
    tools_enabled = agent_config.get("tools_enabled", True)
    tool_block = TOOL_CALLING_ADDENDUM if tools_enabled else ""

    messages = [{
        "role": "system",
        "content": (
            f"{system_prompt}\n\n"
            "CRITICAL GROUNDING RULES:\n"
            "Answer STRICTLY using the Business Context and Relevant business info below. "
            "Do NOT invent or assume details such as hours of operation, pricing, addresses, "
            "phone numbers, or policies if they are not explicitly present in the context. "
            "If the information is not in the context, say you don't have that detail yet and "
            "offer to connect the visitor with the business.\n\n"
            f"Business context: {business_context[:1500]}{rag_block}"
            f"{tool_block}"
            # Placed last so the language rule is the most recent instruction the
            # model reads, and cannot be diluted by the grounding block above.
            f"{lang_svc.reply_directive(lang)}"
        ),
    }]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_message})

    # Non-English replies need more headroom: many scripts cost noticeably more
    # tokens per sentence than English, and a truncated reply reads as a bug.
    budget = 500 if lang["code"] == lang_svc.DEFAULT_LANG else 900
    response = llm(messages, role="chat", max_tokens=budget, temperature=0.6).strip()

    # ── Guardrails: screen output ──
    output_check = screen_output(response)
    if not output_check["safe"]:
        return lang_svc.localize(REFUSAL_MESSAGE, lang)

    return response


# ─── Tool-call utilities (used by main.py or the endpoint handler) ───

def parse_tool_call(response: str) -> dict | None:
    """Extract structured action JSON from agent response, if present."""
    match = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]+?"[^{}]*\}', response)
    if match:
        try:
            data = json.loads(match.group())
            if data.get("action") in SUPPORTED_ACTIONS:
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def validate_tool_call(action: dict) -> dict:
    """Validate that required params are present. Returns {"valid": bool, "error": str}."""
    action_type = action.get("action", "")
    schema = SUPPORTED_ACTIONS.get(action_type)
    if not schema:
        return {"valid": False, "error": f"Unknown action: {action_type}"}
    for param in schema["required"]:
        if param not in action or not action[param]:
            return {"valid": False, "error": f"Missing required param: {param}"}
    return {"valid": True, "error": ""}

