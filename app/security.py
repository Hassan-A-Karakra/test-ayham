import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Depends, Header, HTTPException, status


USERS = {
    "applicant": {"password": "applicant123", "role": "applicant", "name": "Applicant Demo"},
    "staff": {"password": "staff123", "role": "staff", "name": "Registrar Staff"},
    "surveyor": {"password": "surveyor123", "role": "surveyor", "name": "Surveyor Demo"},
    "manager": {"password": "manager123", "role": "manager", "name": "Manager Demo"},
}


def _secret() -> bytes:
    return os.getenv("APP_SECRET", "dev-secret-change-me").encode()


def create_token(username: str, role: str) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + 12 * 60 * 60}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_token(token: str) -> dict[str, Any]:
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return payload


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return verify_token(authorization.removeprefix("Bearer ").strip())


def require_staff(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] not in {"staff", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff access required")
    return user


def require_surveyor_or_staff(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] not in {"surveyor", "staff", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Surveyor or staff access required")
    return user
