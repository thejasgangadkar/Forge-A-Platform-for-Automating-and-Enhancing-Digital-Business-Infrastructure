"""Phase-2 messaging channels: WhatsApp, Telegram and Gmail.

The envelope translation for each is implemented here, because that is the part
which is knowable without an account — the payload shapes are public and stable.
What is deliberately absent is outbound delivery: that needs a Meta Business
account, a bot token or OAuth credentials, so `send()` raises
ChannelNotConfigured rather than pretending to work.

These are not placeholders in the "empty file" sense. Each one parses a real
provider payload into the shared InboundMessage, which means enabling a channel
is a credentials-and-webhook task, not a redesign. That is the claim the PRD
makes about the architecture, and this is what makes it true.
"""
from __future__ import annotations

import os
from typing import Any

from channels.base import ChannelAdapter, ChannelNotConfigured, InboundMessage, OutboundMessage


class WhatsAppAdapter(ChannelAdapter):
    """WhatsApp Cloud API (Meta) webhook format."""

    name = "whatsapp"
    label = "WhatsApp Business"
    enabled = False

    def is_configured(self) -> bool:
        return bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_ID"))

    def verify_webhook(self, params: dict[str, Any]) -> str | None:
        """Meta verifies a webhook by echoing back hub.challenge."""
        expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
        if params.get("hub.mode") == "subscribe" and expected and \
                params.get("hub.verify_token") == expected:
            return params.get("hub.challenge")
        return None

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        # entry[0].changes[0].value.messages[0] — deeply nested, and every level
        # is optional on the status-update callbacks Meta also sends here.
        text, sender = "", None
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            msg = (value.get("messages") or [{}])[0]
            sender = msg.get("from")
            text = (msg.get("text") or {}).get("body", "") or ""
        except (KeyError, IndexError, TypeError):
            pass
        return InboundMessage(
            workspace_id=payload.get("workspace_id", ""),
            text=text.strip(), sender_id=sender, channel=self.name, raw=payload,
        )

    def format_outbound(self, message: OutboundMessage) -> dict[str, Any]:
        return {"messaging_product": "whatsapp", "type": "text",
                "text": {"body": message.text}}

    def send(self, message: OutboundMessage, recipient: str) -> bool:
        if not self.is_configured():
            raise ChannelNotConfigured(
                "WhatsApp needs WHATSAPP_TOKEN and WHATSAPP_PHONE_ID")
        import requests
        phone_id = os.getenv("WHATSAPP_PHONE_ID")
        body = self.format_outbound(message) | {"to": recipient}
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"},
            json=body, timeout=20)
        return r.ok


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API Update format."""

    name = "telegram"
    label = "Telegram"
    enabled = False

    def is_configured(self) -> bool:
        return bool(os.getenv("TELEGRAM_BOT_TOKEN"))

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        msg = payload.get("message") or payload.get("edited_message") or {}
        return InboundMessage(
            workspace_id=payload.get("workspace_id", ""),
            text=(msg.get("text") or "").strip(),
            sender_id=str((msg.get("chat") or {}).get("id") or "") or None,
            channel=self.name, raw=payload,
        )

    def format_outbound(self, message: OutboundMessage) -> dict[str, Any]:
        return {"method": "sendMessage", "text": message.text}

    def send(self, message: OutboundMessage, recipient: str) -> bool:
        if not self.is_configured():
            raise ChannelNotConfigured("Telegram needs TELEGRAM_BOT_TOKEN")
        import requests
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": recipient, "text": message.text},
                          timeout=20)
        return r.ok


class GmailAdapter(ChannelAdapter):
    """Gmail assistant — replies to inbound email.

    Email is turn-based rather than conversational, so a reply carries a subject
    and threading headers that chat channels have no equivalent for.
    """

    name = "gmail"
    label = "Gmail assistant"
    enabled = False

    def is_configured(self) -> bool:
        return bool(os.getenv("GMAIL_CLIENT_ID") and os.getenv("GMAIL_REFRESH_TOKEN"))

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        headers = payload.get("headers") or {}
        body = payload.get("body") or payload.get("snippet") or ""
        return InboundMessage(
            workspace_id=payload.get("workspace_id", ""),
            text=str(body).strip(),
            sender_id=headers.get("From") or payload.get("from"),
            channel=self.name, raw=payload,
        )

    def format_outbound(self, message: OutboundMessage) -> dict[str, Any]:
        subject = (message.raw_subject if hasattr(message, "raw_subject")
                   else "Re: your enquiry")
        return {"subject": subject, "body": message.text,
                "from_name": message.agent_name}

    def send(self, message: OutboundMessage, recipient: str) -> bool:
        if not self.is_configured():
            raise ChannelNotConfigured(
                "Gmail needs GMAIL_CLIENT_ID and GMAIL_REFRESH_TOKEN")
        raise ChannelNotConfigured("Gmail delivery is not implemented in this build")
