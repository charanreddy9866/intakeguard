import pytest

from intakeguard.security import sign, verify_signature
from tests.conftest import HC, NW, auth, deliver


def test_verify_accepts_valid_signature():
    assert verify_signature("s", "100", sign("s", 100, b"x"), b"x", tolerance_seconds=10, now=105) is None


@pytest.mark.parametrize("timestamp,signature,now,reason", [
    (None, "ab", 100, "missing_signature"),
    ("100", None, 100, "missing_signature"),
    ("abc", "ab", 100, "bad_timestamp"),
    ("100", "ab", 1000, "stale_timestamp"),
    ("100", "é" * 64, 100, "bad_signature"),  # non-ASCII must be a clean 403, not a crash
])
def test_verify_rejections(timestamp, signature, now, reason):
    assert verify_signature("s", timestamp, signature, b"x", tolerance_seconds=10, now=now) == reason


def test_timestamp_is_bound_into_the_mac():
    # Re-using a captured signature with a fresh timestamp must fail.
    old_sig = sign("s", 100, b"x")
    assert verify_signature("s", "200", old_sig, b"x", tolerance_seconds=1000, now=200) == "bad_signature"


@pytest.mark.parametrize("headers", [{}, {"authorization": "Bearer wrong"}, {"authorization": "Basic abc"}])
def test_review_routes_require_a_valid_key(client, headers):
    assert client.get(f"/v1/tenants/{NW}/documents", headers=headers).status_code == 401
    assert client.post(f"/v1/tenants/{NW}/documents/D-1/approve", headers=headers).status_code == 401


def test_a_tenant_key_cannot_reach_another_tenant(client, db_path, process_once):
    deliver(client, "D-1", "Intake form. Claimant ID: C-101. Signed 2026-01-01.", HC)
    process_once()
    # Harbor's document, Northwind's key, Harbor's URL: looks like the tenant does not exist.
    assert client.get(f"/v1/tenants/{HC}/documents", headers=auth(NW)).status_code == 404
    assert client.post(f"/v1/tenants/{HC}/documents/D-1/approve", headers=auth(NW)).status_code == 404
    assert client.get(f"/v1/tenants/{NW}/documents", headers=auth(NW)).json() == []
