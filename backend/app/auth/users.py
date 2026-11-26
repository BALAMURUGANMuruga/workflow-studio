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


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    if os.getenv("WORKFLOW_REQUIRE_CONFIGURED_AUTH") == "true":
        configured_name = os.getenv("WORKFLOW_ADMIN_USERNAME", "").strip()
        configured_password = os.getenv("WORKFLOW_ADMIN_PASSWORD", "")
        if not configured_name or len(configured_password) < 16:
            return None
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
