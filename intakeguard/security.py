"""Webhook signatures and API-key checks.

Signature scheme (Stripe-style, synthetic):
    X-Timestamp: unix seconds
    X-Signature: hex HMAC-SHA256(secret, f"{timestamp}.".encode() + raw_body)
Binding the timestamp into the MAC and rejecting stale timestamps blocks replay of captured deliveries.
"""
from __future__ import annotations

import hashlib
import hmac
import time


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    tolerance_seconds: int,
    now: float | None = None,
) -> str | None:
    """Return None if valid, else a short machine-readable reason."""
    if not timestamp or not signature:
        return "missing_signature"
    if not timestamp.isdigit():
        return "bad_timestamp"
    now = time.time() if now is None else now
    if abs(now - int(timestamp)) > tolerance_seconds:
        return "stale_timestamp"
    expected = sign(secret, timestamp, body).encode("ascii")
    # compare bytes: compare_digest raises on non-ASCII str, which would turn garbage into a 500
    if not hmac.compare_digest(expected, signature.strip().lower().encode("utf-8")):
        return "bad_signature"
    return None


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
