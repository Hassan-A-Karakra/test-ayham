from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import LoginRequest
from ..security import USERS, create_token, current_user

router = APIRouter(tags=["Authentication"])


@router.post("/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    user = USERS.get(payload.username)
    if not user or user["password"] != payload.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return {
        "access_token": create_token(payload.username, user["role"]),
        "token_type": "bearer",
        "user": {"username": payload.username, "role": user["role"], "name": user["name"]},
    }


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user
