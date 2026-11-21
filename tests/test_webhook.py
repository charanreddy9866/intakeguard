import sqlite3
import threading
import time

import pytest

from intakeguard.extractors import rules
from tests.conftest import HC, NW, SECRET, body, deliver, signed_headers

URL = "/v1/webhooks/documents"


def rows(db_path, sql, *args):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(sql, args).fetchall()


def test_signed_delivery_is_stored_as_received(client, db_path):
    r = deliver(client, "D-1", "Intake form. Claimant ID: C-101.")
    assert r.status_code == 200
    assert r.json() == {"document_id": "D-1", "status": "received", "duplicate": False}
    assert rows(db_path, "SELECT tenant, status FROM documents") == [(NW, "received")]


@pytest.mark.parametrize("case", ["missing", "wrong_hex", "garbage", "other_tenant_secret",
                                  "signed_different_bytes", "truncated"])
def test_bad_signature_rejected(client, db_path, case):
    raw = body("D-1", "text")
    headers = signed_headers(raw)
    if case == "missing":
        del headers["x-signature"]
    elif case == "wrong_hex":
        headers["x-signature"] = "0" * 64
    elif case == "garbage":
        headers["x-signature"] = "not-a-signature"
    elif case == "other_tenant_secret":
        headers = signed_headers(raw, secret=SECRET[HC])
    elif case == "signed_different_bytes":
        headers = signed_headers(body("D-1", "other text"))
    elif case == "truncated":
        headers["x-signature"] = headers["x-signature"][:-2]
    r = client.post(URL, content=raw, headers=headers)
    assert r.status_code == 403
    assert rows(db_path, "SELECT COUNT(*) FROM documents") == [(0,)]


def test_stale_timestamp_rejected_to_block_replay(client, db_path):
    raw = body("D-1", "text")
    r = client.post(URL, content=raw, headers=signed_headers(raw, ts=int(time.time()) - 3600))
    assert r.status_code == 403 and r.json()["error"] == "stale_timestamp"
    assert rows(db_path, "SELECT COUNT(*) FROM documents") == [(0,)]


def test_signature_covers_raw_bytes_not_parsed_json(client):
    compact = body("D-1", "text")
    spaced = compact.replace(b":", b": ")
    r = client.post(URL, content=spaced, headers=signed_headers(compact))
    assert r.status_code == 403


def test_uppercase_hex_signature_accepted(client):
    raw = body("D-1", "text")
    headers = signed_headers(raw)
    headers["x-signature"] = headers["x-signature"].upper()
    assert client.post(URL, content=raw, headers=headers).status_code == 200


@pytest.mark.parametrize("raw", [
    b"not json", b"[]", b'{"inbox":"intake@northwind-legal.example","text":"x"}',
    b'{"document_id":1,"inbox":"intake@northwind-legal.example","text":"x"}',
    b'{"document_id":"","inbox":"intake@northwind-legal.example","text":"x"}',
    b'{"document_id":"has space","inbox":"intake@northwind-legal.example","text":"x"}',
    b'{"document_id":"D-1","inbox":"intake@northwind-legal.example","text":"\\ud800"}',
])
def test_malformed_body_returns_400_before_auth(client, raw):
    assert client.post(URL, content=raw, headers={"content-type": "application/json"}).status_code == 400


def test_unknown_inbox_returns_404(client):
    raw = body("D-1", "x", inbox="intake@nobody.example")
    assert client.post(URL, content=raw, headers=signed_headers(raw)).status_code == 404


def test_oversized_body_returns_413(client):
    raw = body("D-1", "x" * 1_100_000)
    assert client.post(URL, content=raw, headers=signed_headers(raw)).status_code == 413


def test_duplicate_document_id_stored_once_and_original_kept(client, db_path):
    assert deliver(client, "D-1", "original").status_code == 200
    r = deliver(client, "D-1", "replacement")
    assert r.status_code == 200 and r.json()["duplicate"] is True
    assert rows(db_path, "SELECT text FROM documents") == [("original",)]


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_duplicate_delivery_stores_one_row(new_client, db_path, attempt):
    barrier, codes = threading.Barrier(2), []

    def send(text):
        c = new_client()
        raw = body("D-RACE", text)
        headers = signed_headers(raw)
        barrier.wait()
        codes.append(c.post(URL, content=raw, headers=headers).status_code)

    threads = [threading.Thread(target=send, args=(t,)) for t in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200]
    assert rows(db_path, "SELECT COUNT(*) FROM documents WHERE document_id='D-RACE'") == [(1,)]


def test_same_document_id_is_separate_per_tenant(client, db_path):
    deliver(client, "D-1", "northwind text", NW)
    deliver(client, "D-1", "harbor text", HC)
    assert sorted(rows(db_path, "SELECT tenant, text FROM documents")) == [(HC, "harbor text"), (NW, "northwind text")]


def test_webhook_never_calls_extractor(client, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("extractor called from webhook")
    monkeypatch.setattr(rules.RulesExtractor, "extract", boom)
    assert deliver(client, "D-1", "Intake form").status_code == 200


def test_request_id_is_echoed(client):
    r = client.get("/healthz", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123" and r.json() == {"status": "ok"}
