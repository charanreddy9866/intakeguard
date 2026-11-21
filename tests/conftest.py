from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from intakeguard import metrics
from intakeguard.api import create_app
from intakeguard.security import sign
from intakeguard.worker import process_once as _process_once

NW, HC = "northwind-legal", "harbor-claims"
INBOX = {NW: "intake@northwind-legal.example", HC: "intake@harbor-claims.example"}
SECRET = {NW: "northwind-demo-secret", HC: "harbor-demo-secret"}
KEY = {NW: "nw-demo-api-key", HC: "hc-demo-api-key"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("INTAKEGUARD_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("INTAKEGUARD_EXTRACTOR", "rules")
    metrics.reset()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def app(db_path):
    return create_app(db_path)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def new_client(app):
    return lambda: TestClient(app)


def body(document_id: str, text: str, tenant: str = NW, inbox: str | None = None) -> bytes:
    return json.dumps({"document_id": document_id, "inbox": inbox or INBOX[tenant], "text": text}).encode()


def signed_headers(raw: bytes, tenant: str = NW, ts: int | None = None, secret: str | None = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    return {"content-type": "application/json", "x-timestamp": str(ts),
            "x-signature": sign(secret or SECRET[tenant], ts, raw)}


def deliver(client, document_id: str, text: str, tenant: str = NW):
    raw = body(document_id, text, tenant)
    return client.post("/v1/webhooks/documents", content=raw, headers=signed_headers(raw, tenant))


def auth(tenant: str = NW) -> dict:
    return {"authorization": f"Bearer {KEY[tenant]}"}


@pytest.fixture
def process_once(db_path):
    def run(**kwargs):
        kwargs.setdefault("sleep", lambda _s: None)
        return _process_once(db_path, **kwargs)
    return run
