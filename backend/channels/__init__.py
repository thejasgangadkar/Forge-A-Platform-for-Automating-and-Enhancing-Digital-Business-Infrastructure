"""Channel adapters — deliver the same agent over different transports.

The agent runtime has no knowledge of HTTP, webhooks or message formats, so a new
channel is an envelope translator rather than a second implementation of the
agent. `web` is live; `whatsapp`, `telegram` and `gmail` parse real provider
payloads but are not enabled until credentials are supplied.
"""
from channels.base import (
    ChannelAdapter,
    ChannelNotConfigured,
    InboundMessage,
    OutboundMessage,
    friendly_action_reply,
)
from channels.registry import (
    DEFAULT_CHANNEL,
    enabled_channels,
    get_adapter,
    list_channels,
)

__all__ = [
    "ChannelAdapter",
    "ChannelNotConfigured",
    "InboundMessage",
    "OutboundMessage",
    "friendly_action_reply",
    "DEFAULT_CHANNEL",
    "get_adapter",
    "list_channels",
    "enabled_channels",
]
