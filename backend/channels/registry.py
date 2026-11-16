"""Channel registry — the single place that knows which channels exist."""
from __future__ import annotations

from channels.base import ChannelAdapter
from channels.messaging import GmailAdapter, TelegramAdapter, WhatsAppAdapter
from channels.web import WebChannelAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    a.name: a for a in (
        WebChannelAdapter(),
        WhatsAppAdapter(),
        TelegramAdapter(),
        GmailAdapter(),
    )
}

DEFAULT_CHANNEL = "web"


def get_adapter(name: str | None = None) -> ChannelAdapter:
    """Look up an adapter, defaulting to the web channel."""
    adapter = _ADAPTERS.get((name or DEFAULT_CHANNEL).lower())
    if adapter is None:
        raise KeyError(f"Unknown channel '{name}'")
    return adapter


def list_channels() -> list[dict]:
    """Describe every channel, for the UI and for status reporting.

    `enabled` means shipped in this build; `configured` means this deployment
    also holds the credentials. Both are reported because "not built yet" and
    "built but no API key" need different actions.
    """
    return [
        {
            "name": a.name,
            "label": a.label,
            "enabled": a.enabled,
            "configured": a.is_configured(),
            "status": ("live" if a.enabled and a.is_configured()
                       else "needs credentials" if a.enabled
                       else "planned"),
        }
        for a in _ADAPTERS.values()
    ]


def enabled_channels() -> list[str]:
    return [a.name for a in _ADAPTERS.values() if a.enabled and a.is_configured()]
