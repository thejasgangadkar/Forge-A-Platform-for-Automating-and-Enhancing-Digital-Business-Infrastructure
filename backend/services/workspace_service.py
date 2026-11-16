"""Workspace + conversation + asset persistence (Supabase).

Uses the service-role key (backend), so RLS is bypassed; we enforce user
ownership explicitly by always filtering on user_id.
"""
import os
import json
from database.supabase_client import get_supabase
from rag.vector_store import vector_store


def create_workspace(user_id: str, business_name: str, description: str = "",
                     business_profile: dict | None = None, url: str = "") -> dict:
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "business_name": business_name,
        "name": business_name,           # legacy column kept in sync
        "description": description,
        "business_profile": business_profile or {},
        "url": url,
        "status": "active",
    }
    res = sb.table("workspaces").insert(row).execute()
    ws = res.data[0]
    # Seed RAG memory with the business profile/description.
    try:
        if description:
            vector_store.add_business_context(ws["id"], description,
                                              {"workspace_id": ws["id"]})
    except Exception as e:
        print(f"[workspace] rag seed failed: {e}")
    return ws


def list_workspaces(user_id: str) -> list[dict]:
    sb = get_supabase()
    return (sb.table("workspaces").select("*")
            .eq("user_id", user_id).order("created_at", desc=True).execute().data)


def _is_uuid(value: str) -> bool:
    """Workspace ids are UUIDs. Anything else can't exist, so don't ask Postgres.

    Public endpoints take the workspace id straight from the URL, and sending a
    malformed value to a uuid column makes the driver raise, which surfaced as an
    HTTP 500 instead of a clean 404.
    """
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def get_workspace(workspace_id: str, user_id: str | None = None) -> dict | None:
    if not _is_uuid(workspace_id):
        return None
    sb = get_supabase()
    q = sb.table("workspaces").select("*").eq("id", workspace_id)
    if user_id:
        q = q.eq("user_id", user_id)
    res = q.execute()
    return res.data[0] if res.data else None


def update_workspace(workspace_id: str, fields: dict) -> dict | None:
    sb = get_supabase()
    res = sb.table("workspaces").update(fields).eq("id", workspace_id).execute()
    return res.data[0] if res.data else None


def delete_workspace(workspace_id: str, user_id: str) -> dict:
    """Delete a workspace and everything belonging to it.

    A workspace spans three stores, so removing the database row alone would
    leave the generated site still being served and the RAG memory still
    answering queries. Each store is cleaned independently and failures are
    collected rather than raised, so one stubborn artifact cannot leave the
    account with an undeletable workspace.

    Ownership is verified first: the id comes from a URL and must never allow
    deleting another account's data.
    """
    ws = get_workspace(workspace_id, user_id)
    if not ws:
        return {"ok": False, "error": "Workspace not found"}

    removed, problems = [], []
    sb = get_supabase()

    # 1. Vector memory. Chroma is keyed by business_id, and the scrape may have
    #    been stored under a temporary ref before being copied onto this id.
    try:
        n = vector_store.delete_context(workspace_id)
        removed.append(f"{n} memory chunk(s)")
    except Exception as e:
        problems.append(f"vector memory: {e}")

    # 2. Generated files. asset_dir normally equals the workspace id, but older
    #    workspaces recorded a separate directory.
    try:
        import shutil
        from services.generation_service import WORKSPACES_DIR
        asset_dir = (ws.get("business_profile") or {}).get("asset_dir") or workspace_id
        target = os.path.join(WORKSPACES_DIR, asset_dir)
        # Refuse anything that escapes the workspaces directory.
        root = os.path.realpath(WORKSPACES_DIR)
        full = os.path.realpath(target)
        if not full.startswith(root + os.sep):
            problems.append("generated files: unsafe path, skipped")
        elif os.path.isdir(full):
            shutil.rmtree(full)
            removed.append("generated files")
    except Exception as e:
        problems.append(f"generated files: {e}")

    # 3. Child rows. The schema declares ON DELETE CASCADE, but they are removed
    #    explicitly so the outcome does not depend on the deployed schema being
    #    exactly in sync with schema.sql.
    for table in ("analytics_events", "agent_actions", "assets", "conversations"):
        try:
            sb.table(table).delete().eq("workspace_id", workspace_id).execute()
        except Exception as e:
            problems.append(f"{table}: {e}")

    # 4. The workspace row itself, still scoped to the owner.
    try:
        sb.table("workspaces").delete().eq("id", workspace_id).eq("user_id", user_id).execute()
        removed.append("workspace")
    except Exception as e:
        return {"ok": False, "error": f"Could not delete workspace: {e}",
                "removed": removed, "problems": problems}

    return {"ok": True, "removed": removed, "problems": problems,
            "business_name": ws.get("business_name")}


# ─── conversations ──────────────────────────────────────────────────
def add_message(workspace_id: str, role: str, content: str) -> None:
    sb = get_supabase()
    sb.table("conversations").insert({
        "workspace_id": workspace_id, "role": role, "content": content,
    }).execute()


def get_messages(workspace_id: str, limit: int = 200) -> list[dict]:
    sb = get_supabase()
    return (sb.table("conversations").select("*")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=False).limit(limit).execute().data)


# ─── assets ─────────────────────────────────────────────────────────
def add_asset(workspace_id: str, asset_type: str, name: str,
              path: str = "", config: dict | None = None) -> dict:
    sb = get_supabase()
    res = sb.table("assets").insert({
        "workspace_id": workspace_id, "type": asset_type,
        "name": name, "path": path, "config": config or {},
    }).execute()
    return res.data[0]


def get_assets(workspace_id: str, asset_type: str | None = None) -> list[dict]:
    sb = get_supabase()
    q = sb.table("assets").select("*").eq("workspace_id", workspace_id)
    if asset_type:
        q = q.eq("type", asset_type)
    return q.execute().data


def get_agent_configs(workspace_id: str) -> list[dict]:
    """Return stored agent configs for a workspace (from assets, else file)."""
    assets = get_assets(workspace_id, "agent")
    if assets:
        return [a["config"] for a in assets if a.get("config")]
    # fallback to file
    from services.generation_service import WORKSPACES_DIR
    p = os.path.join(WORKSPACES_DIR, workspace_id, "agents", "agents.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return []
    return []
