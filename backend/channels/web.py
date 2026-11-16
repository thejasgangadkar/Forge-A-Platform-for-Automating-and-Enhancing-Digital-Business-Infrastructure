"""Web channel — the in-app sandbox, the hosted page and the embed widget.

The only channel enabled today, and the one the live agent endpoint runs through.
Its payload is already close to the normalised form, which is exactly why it is a
useful reference implementation: whatever extra work a WhatsApp or Telegram
adapter has to do is confined to its own parse/format methods.
"""
from __future__ import annotations

from typing import Any

from channels.base import ChannelAdapter, InboundMessage, OutboundMessage


class WebChannelAdapter(ChannelAdapter):
    name = "web"
    label = "Website & hosted page"
    enabled = True

    def is_configured(self) -> bool:
        # Served by this application, so there are no external credentials.
        return True

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        history = payload.get("history") or []
        # Only keep well-formed turns: a malformed history would otherwise be
        # passed straight to the model.
        clean = [
            {"role": h["role"], "content": h["content"]}
            for h in history
            if isinstance(h, dict) and h.get("role") and h.get("content")
        ]
        return InboundMessage(
            workspace_id=payload.get("workspace_id", ""),
            text=(payload.get("message") or "").strip(),
            history=clean,
            agent_id=payload.get("agent_id"),
            sender_id=None,          # web visitors are anonymous
            channel=self.name,
            # The widget and hosted page send the browser locale they are using
            # for speech, so text and voice stay in the same language.
            language=payload.get("language") or payload.get("locale"),
            raw=payload,
        )

    def format_outbound(self, message: OutboundMessage) -> dict[str, Any]:
        # Response shape kept identical to the pre-adapter endpoint so the
        # existing widget, hosted page and sandbox keep working unchanged.
        return {
            "reply": message.text,
            "agent": message.agent_name,
            "tool_call": message.tool_call,
        }
