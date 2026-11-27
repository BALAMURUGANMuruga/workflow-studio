# Expose login and account endpoints and resolve the signed bearer token for protected routes.
"""Auth HTTP routes and dependency helpers."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field

from .tokens import issue_token, verify_token
from .users import AuthConfigurationError, authenticate

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    displayName: str


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_token(token)
    if not claims:
        raise HTTPException(401, "Invalid or expired token")
    return claims


def require_master(user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    if user.get("role") != "master":
        raise HTTPException(403, "Master role required")
    return user


@router.post("/login", response_model=LoginResponse)
def login(body: LoginBody):
    try:
        user = authenticate(body.username, body.password)
    except AuthConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = issue_token({"sub": user["username"], "role": user["role"], "name": user["displayName"]})
    return LoginResponse(
        token=token,
        username=user["username"],
        role=user["role"],
        displayName=user["displayName"],
    )


@router.get("/me")
def me(user: Annotated[dict[str, Any], Depends(get_current_user)]):
    return {
        "username": user.get("sub"),
        "role": user.get("role"),
        "displayName": user.get("name"),
    }


@router.post("/logout")
def logout():
    # Stateless tokens — client discards token
    return {"ok": True}
