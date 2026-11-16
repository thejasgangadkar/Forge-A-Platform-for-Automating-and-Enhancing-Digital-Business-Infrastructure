"""Analytics Service — tracks and aggregates workspace events.

Events: visit (site page load), chat (agent conversation), lead (captured via tool-call).
Designed as fire-and-forget (non-blocking, exceptions caught and logged).
"""
import logging
from datetime import datetime, timedelta, timezone
from database.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def track_event(workspace_id: str, event_type: str, metadata: dict | None = None):
    """Record an analytics event. Fire-and-forget: catches all exceptions."""
    try:
        get_supabase().table("analytics_events").insert({
            "workspace_id": workspace_id,
            "event_type": event_type,
            "metadata": metadata or {},
        }).execute()
    except Exception as e:
        logger.warning(f"[analytics] Failed to track event: {e}")


def get_analytics(workspace_id: str, period: str = "week") -> dict:
    """Get aggregated analytics for a workspace.

    Args:
        workspace_id: UUID of the workspace
        period: "day" | "week" | "month"

    Returns: {"total_visits": int, "total_chats": int, "total_leads": int, "events": [...]}
    """
    try:
        # Calculate the start date based on period
        now = datetime.now(timezone.utc)
        if period == "day":
            start = now - timedelta(days=1)
        elif period == "month":
            start = now - timedelta(days=30)
        else:  # week (default)
            start = now - timedelta(days=7)

        result = get_supabase().table("analytics_events")\
            .select("*")\
            .eq("workspace_id", workspace_id)\
            .gte("created_at", start.isoformat())\
            .order("created_at", desc=True)\
            .execute()

        events = result.data or []

        return {
            "total_visits": sum(1 for e in events if e.get("event_type") == "visit"),
            "total_chats": sum(1 for e in events if e.get("event_type") == "chat"),
            "total_leads": sum(1 for e in events if e.get("event_type") == "lead"),
            "period": period,
            "events": events[:100],  # cap at 100 for the response
        }
    except Exception as e:
        logger.warning(f"[analytics] Failed to get analytics: {e}")
        return {"total_visits": 0, "total_chats": 0, "total_leads": 0, "period": period, "events": []}
