# Handle user records and credential checks for assistant authentication.
"""In-memory demo users. Replace with DB in production."""
from __future__ import annotations

import os
from hmac import compare_digest

from typing import Any

# password is plain for demo only — hash in real deployments
USERS: dict[str, dict[str, Any]] = {
    "customer": {
        "username": "customer",
        "password": "customer123",
        "role": "customer",
        "displayName": "Customer User",
    },
    "master": {
        "username": "master",
        "password": "master123",
        "role": "master",
        "displayName": "Master Admin",
    },
    "admin": {
        "username": "admin",
        "password": "admin123",
        "role": "master",
        "displayName": "Administrator",
    },
}


class AuthConfigurationError(RuntimeError):
    """The hosted sign-in account is configured incorrectly."""


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    if os.getenv("WORKFLOW_REQUIRE_CONFIGURED_AUTH") == "true":
        configured_name = os.getenv("WORKFLOW_ADMIN_USERNAME", "").strip()
        configured_password = os.getenv("WORKFLOW_ADMIN_PASSWORD", "")
        if not 1 <= len(configured_name) <= 64 or not 16 <= len(configured_password) <= 128:
            raise AuthConfigurationError(
                "Hosted sign-in is unavailable. Set WORKFLOW_ADMIN_USERNAME and a "
                "16–128 character WORKFLOW_ADMIN_PASSWORD in Render."
            )
        username_matches = compare_digest(username.strip().casefold().encode(), configured_name.casefold().encode())
        password_matches = compare_digest(password.encode(), configured_password.encode())
        if username_matches and password_matches:
            return {"username": configured_name, "role": "master", "displayName": configured_name}
        return None

    user = USERS.get((username or "").strip().casefold())
    if not user:
        # also allow exact key match
        user = USERS.get((username or "").strip())
    if not user or user["password"] != password:
        return None
    return {
        "username": user["username"],
        "role": user["role"],
        "displayName": user["displayName"],
    }
