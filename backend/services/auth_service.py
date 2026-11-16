"""Auth helper — validates Supabase access tokens and returns the user id.

The frontend signs in with Supabase Auth and sends the access token as
`Authorization: Bearer <token>`. We validate it via the Supabase client.
"""
from fastapi import Header, HTTPException
from database.supabase_client import get_supabase


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return authorization


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: returns {'id', 'email'} or raises 401."""
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing auth token")
    try:
        sb = get_supabase()
        res = sb.auth.get_user(token)
        user = getattr(res, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": user.id, "email": getattr(user, "email", None)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth failed: {e}")


async def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None
