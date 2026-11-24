"""Session, auth-guard and input-safety helpers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status

from .config import settings
from .crypto import random_token
from .db import execute, query_one, utcnow


def create_session(user_id: int, request: Request | None = None) -> tuple[str, datetime]:
    token = random_token(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.SESSION_DAYS)
    execute(
        "INSERT INTO sessions(id, user_id, created_at, expires_at, user_agent) VALUES (?,?,?,?,?)",
        (
            token,
            user_id,
            utcnow(),
            expires.isoformat(timespec="seconds"),
            (request.headers.get("user-agent", "")[:300] if request else None),
        ),
    )
    return token, expires


def destroy_session(token: str) -> None:
    if token:
        execute("DELETE FROM sessions WHERE id=?", (token,))


def set_session_cookie(response: Response, token: str, expires: datetime) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=int((expires - datetime.now(timezone.utc)).total_seconds()),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE, path="/")


def get_session_token(request: Request) -> Optional[str]:
    token = request.cookies.get(settings.SESSION_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_user_optional(request: Request) -> Optional[dict[str, Any]]:
    token = get_session_token(request)
    if not token:
        return None
    row = query_one(
        """SELECT s.id AS session_id, s.expires_at, u.*
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.id=?""",
        (token,),
    )
    if not row:
        return None
    expires_at = row.get("expires_at") or ""
    try:
        if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
            destroy_session(token)
            return None
    except ValueError:
        return None
    return row


def require_user(request: Request) -> dict[str, Any]:
    user = current_user_optional(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


UserDep = Depends(require_user)


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(value: str | None, max_len: int = 5000) -> str:
    if not value:
        return ""
    return _CTRL.sub("", str(value)).strip()[:max_len]


def ensure_owned(table: str, row_id: int, user_id: int) -> dict[str, Any]:
    row = query_one(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (row_id, user_id))
    if not row:
        raise HTTPException(status_code=404, detail=f"{table} row {row_id} not found")
    return row
