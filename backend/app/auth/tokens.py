"""Simple HMAC token (stdlib only — no external JWT dependency required)."""
# Postpone evaluation of type annotations.
from __future__ import annotations

# Authentication uses Python standard-library modules. AI and retrieval run elsewhere.

# Encode binary data as URL-safe Base64 text and decode it back.
import base64
# Provide the SHA-256 hash function used by HMAC.
import hashlib
# Sign and verify data with a shared secret.
import hmac
# Convert claim dictionaries to JSON text and back.
import json
# Read configuration from environment variables.
import os
# Read the current Unix time in seconds.
import time
# Allow claim values of different types in the type annotation.
from typing import Any

# Read the signing key. The fallback is for development. Set a private key in deployed environments.
SECRET = os.getenv("WORKFLOW_AUTH_SECRET", "workflow-studio-dev-secret-change-me")
# Read the token lifetime in seconds. The default is 86,400 seconds (24 hours).
TOKEN_TTL_SECONDS = int(os.getenv("WORKFLOW_AUTH_TTL", "86400"))  # 24h


# Input: bytes. Output: URL-safe Base64 text without padding.
def _b64(data: bytes) -> str:
    # Encode the bytes, remove trailing padding, and convert the result to an ASCII string.
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# Input: unpadded Base64 text. Output: decoded bytes.
def _unb64(data: str) -> bytes:
    # Compute the padding needed to reach a multiple of four characters.
    pad = "=" * (-len(data) % 4)
    # Decode the padded text back to its original bytes.
    return base64.urlsafe_b64decode(data + pad)


# Input: login claims such as sub, role, and name. Output: a signed token string.
def issue_token(claims: dict[str, Any]) -> str:
    payload = {
        # Copy the caller's claims into a new dictionary.
        **claims,
        # Record the issuance time as a Unix timestamp.
        "iat": int(time.time()),
        # Set the expiry timestamp. These timestamp fields override any supplied by the caller.
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    # Serialize the claims as compact JSON, encode them as UTF-8, then convert them to Base64.
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    # Sign the encoded body with HMAC-SHA256 and encode the signature as Base64.
    sig = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
    # Return two dot-separated parts. The body is readable Base64 and the signature authenticates it.
    return f"{body}.{sig}"


# Input: the raw bearer token string. Output: verified claims or None when rejected.
def verify_token(token: str) -> dict[str, Any] | None:
    try:
        # Split the token into its body and signature at the first dot.
        body, sig = token.split(".", 1)
    # A token without the separator cannot be unpacked into two parts.
    except ValueError:
        # Tell the authentication route to reject the token.
        return None
    # Recompute the signature using the received body and configured signing key.
    expected = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
    # Compare signatures using a timing-resistant comparison.
    if not hmac.compare_digest(expected, sig):
        # Reject a signature mismatch before decoding the claims.
        return None
    try:
        # Decode the Base64 body, read it as UTF-8 text, then parse the JSON.
        payload = json.loads(_unb64(body).decode("utf-8"))
    # Reject decoding and JSON parsing errors.
    except (ValueError, json.JSONDecodeError):
        # Return None when the payload cannot be decoded.
        return None
    # Ensure the JSON result is an object suitable for use as a claims dictionary.
    if not isinstance(payload, dict):
        # Reject JSON arrays, strings, and other non-object values.
        return None
    # Read the expiry as an integer and compare it with the current time. A missing expiry defaults to zero.
    if int(payload.get("exp", 0)) < int(time.time()):
        # Reject expired claims.
        return None
    # Return claims to the authentication route for downstream access checks.
    return payload
