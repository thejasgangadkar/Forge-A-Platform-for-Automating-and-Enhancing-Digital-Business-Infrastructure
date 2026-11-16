"""Channel abstraction for agent conversations.

An agent turn is the same work regardless of where the message arrived from:
resolve which agent should answer, run it with RAG grounding, execute any
tool-call it emits, record analytics, and hand back a reply. Only the envelope
differs — a web widget posts JSON, WhatsApp posts a Meta webhook, Telegram posts
an Update, Gmail delivers a MIME message.

So that logic lives here once, in `ChannelAdapter.handle_turn()`, and each
channel only implements the two translation steps it actually owns:
`parse_inbound()` and `format_outbound()`. Adding a channel therefore means
writing an envelope translator, not reimplementing the agent pipeline.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    """A visitor message, normalised away from any channel's payload shape."""
    workspace_id: str
    text: str
    history: list[dict[str, str]] = field(default_factory=list)
    agent_id: str | None = None
    # Channel-native identity (phone number, chat id, email address). Used for
    # replying and for attributing leads; None for anonymous web visitors.
    sender_id: str | None = None
    channel: str = "web"
    # Language hint from the channel (a browser locale, a WhatsApp profile
    # locale). Only a hint: the runtime still detects from the message text,
    # because a visitor's device locale often is not the language they type in.
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """An agent reply, before it is rendered into a channel's format."""
    text: str
    agent_name: str = "Assistant"
    tool_call: dict[str, Any] | None = None
    workspace_id: str = ""
    channel: str = "web"


class ChannelNotConfigured(RuntimeError):
    """Raised when an adapter exists but its credentials are absent.

    Distinguishes "this channel is not part of the build" from "this channel is
    implemented but the deployment has not been given its API keys", which are
    very different problems for whoever is operating the platform.
    """


class ChannelAdapter(abc.ABC):
    """Base class for every delivery channel."""

    #: Stable identifier used in the registry, URLs and analytics.
    name: str = "base"
    #: Human-readable label for the UI.
    label: str = "Channel"
    #: False for channels that are designed but not yet released.
    enabled: bool = False

    # ── the two things a channel actually owns ────────────────────────
    @abc.abstractmethod
    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        """Translate this channel's payload into an InboundMessage."""

    @abc.abstractmethod
    def format_outbound(self, message: OutboundMessage) -> dict[str, Any]:
        """Render a reply into the response body this channel expects."""

    # ── optional hooks ───────────────────────────────────────────────
    def is_configured(self) -> bool:
        """Whether this deployment has the credentials to use the channel."""
        return self.enabled

    def verify_webhook(self, params: dict[str, Any]) -> str | None:
        """Answer a provider's webhook verification handshake, if it has one."""
        return None

    def send(self, message: OutboundMessage, recipient: str) -> bool:
        """Push a message out of band.

        Web channels answer inline in the HTTP response, so they never need this.
        Messaging channels must override it to call their provider's send API.
        """
        raise ChannelNotConfigured(
            f"{self.name} cannot send outbound messages in this build")

    # ── the shared pipeline (identical for every channel) ─────────────
    def handle_turn(self, inbound: InboundMessage) -> OutboundMessage:
        """Run one agent turn. Channel-independent by construction."""
        # Imported lazily so this module stays importable in isolation and to
        # avoid a cycle: main -> channels -> services -> main.
        from services import workspace_service as ws_svc
        from services.agent_runtime import run_agent, parse_tool_call, validate_tool_call
        from services.analytics_service import track_event

        ws = ws_svc.get_workspace(inbound.workspace_id)
        if not ws:
            raise LookupError("Workspace not found")

        track_event(inbound.workspace_id, "chat",
                    {"agent_id": inbound.agent_id, "channel": self.name})

        cfg = self._resolve_agent(inbound, ws_svc)

        # Resolve the visitor's language once, here, so the reply, any action
        # confirmation, and the analytics record all agree on it.
        from services import language_service as lang_svc
        profile = ws.get("business_profile") or {}
        lang = lang_svc.analyze(
            inbound.text,
            declared=inbound.language or cfg.get("language") or profile.get("language"),
        )

        reply = run_agent(
            cfg,
            ws.get("description", "") or ws.get("business_name", "") or "",
            inbound.text,
            history=inbound.history,
            workspace_id=inbound.workspace_id,
            language=lang,
        )

        tool_call = parse_tool_call(reply)
        if tool_call and validate_tool_call(tool_call)["valid"]:
            self._record_action(inbound, cfg, tool_call, track_event)
            # Visitors should never see raw action JSON. The confirmation replaces
            # the model's own words, so it has to be localised too or a Hindi
            # conversation would suddenly answer a booking in English.
            reply = friendly_action_reply(tool_call, lang)

        return OutboundMessage(
            text=reply,
            agent_name=cfg.get("name", "Assistant"),
            tool_call=tool_call,
            workspace_id=inbound.workspace_id,
            channel=self.name,
        )

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _resolve_agent(inbound: InboundMessage, ws_svc) -> dict:
        """Pick the agent to answer with, falling back to a usable default."""
        configs = ws_svc.get_agent_configs(inbound.workspace_id)
        if inbound.agent_id:
            match = next((c for c in configs if c.get("id") == inbound.agent_id), None)
            if match:
                return match
        if configs:
            return configs[0]
        return {"system_prompt": "You are a helpful customer support agent.",
                "type": "support", "name": "Assistant"}

    def _record_action(self, inbound: InboundMessage, cfg: dict,
                       tool_call: dict, track_event) -> None:
        """Persist an executed tool-call. Never blocks the reply."""
        try:
            from database.supabase_client import get_supabase
            payload = dict(tool_call)
            payload["channel"] = self.name
            if inbound.sender_id:
                payload.setdefault("contact", inbound.sender_id)
            get_supabase().table("agent_actions").insert({
                "workspace_id": inbound.workspace_id,
                "agent_id": cfg.get("id", "default"),
                "action_type": tool_call["action"],
                "payload": payload,
                "status": "completed",
            }).execute()
            if tool_call["action"] == "capture_lead":
                track_event(inbound.workspace_id, "lead", payload)
        except Exception as e:
            # A storage failure must not cost the visitor their answer.
            print(f"[channels] could not record action: {e}")


def friendly_action_reply(tool_call: dict, language=None) -> str:
    """Turn a structured tool-call into a natural confirmation sentence.

    `language` may be a code or an analysed language dict. The sentence is
    composed in English and then localised, so the values the visitor supplied
    (their name, the service, the time) are substituted before translation and
    survive it intact.
    """
    action = tool_call.get("action")
    if action == "book_slot":
        when = tool_call.get("time", "your requested time")
        name = tool_call.get("name", "")
        service = tool_call.get("service", "appointment")
        who = f", {name}" if name else ""
        text = (f"All set{who}! I've booked your {service} for {when}. "
                "You'll receive a confirmation shortly. "
                "Is there anything else I can help with?")
    elif action == "capture_lead":
        name = tool_call.get("name", "")
        who = f", {name}" if name else ""
        text = (f"Thanks{who}! I've saved your details and someone from the team "
                "will reach out to you soon. Anything else I can help with?")
    elif action == "escalate":
        text = ("I've passed this along to a team member who will follow up with "
                "you directly. Is there anything else I can do in the meantime?")
    else:
        text = "Done! Is there anything else I can help you with?"

    if not language:
        return text
    from services import language_service as lang_svc
    return lang_svc.localize(text, language)
