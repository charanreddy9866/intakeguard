import sqlite3

from fastapi.testclient import TestClient

from intakeguard.api import create_app
from tests.conftest import auth


def test_demo_mode_seeds_a_populated_queue_once(monkeypatch, db_path):
    monkeypatch.setenv("INTAKEGUARD_DEMO", "1")
    client = TestClient(create_app(db_path))
    create_app(db_path)  # a restart must not duplicate anything
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 10
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE status='received'").fetchone()[0] == 0
    queue = client.get("/v1/tenants/northwind-legal/documents?needs_review=true", headers=auth()).json()
    reasons = {r for d in queue for r in d["review_reasons"]}
    assert {"possible_prompt_injection", "no_claimant", "date_not_a_calendar_date", "claimant_not_in_tenant"} <= reasons
    page = client.get("/review").text
    assert "Live demo with synthetic data" in page


def test_without_demo_mode_nothing_is_seeded_and_no_banner(client, db_path):
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert "Live demo" not in client.get("/review").text


def test_root_redirects_to_review(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/review"
