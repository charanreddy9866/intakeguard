import sqlite3
import threading

import pytest

from tests.conftest import NW, auth, deliver

GOOD = "Intake form. Claimant ID: C-101. Signed 2026-01-01."


def count(db_path, sql):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(sql).fetchone()[0]


def approve(client, document_id, tenant=NW):
    return client.post(f"/v1/tenants/{tenant}/documents/{document_id}/approve", headers=auth(tenant))


def test_approve_files_the_document(client, db_path, process_once):
    deliver(client, "D-1", GOOD)
    process_once()
    r = approve(client, "D-1")
    assert r.status_code == 200 and r.json() == {"document_id": "D-1", "claimant_id": "C-101", "status": "filed"}
    assert count(db_path, "SELECT COUNT(*) FROM case_file_entries") == 1


def test_approve_twice_one_entry(client, db_path, process_once):
    deliver(client, "D-1", GOOD)
    process_once()
    assert approve(client, "D-1").status_code == 200
    assert approve(client, "D-1").status_code == 200
    assert count(db_path, "SELECT COUNT(*) FROM case_file_entries") == 1
    assert count(db_path, "SELECT COUNT(*) FROM audit_log WHERE event='filed'") == 1


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_approve_one_entry(new_client, client, db_path, process_once, attempt):
    deliver(client, "D-1", GOOD)
    process_once()
    barrier, codes = threading.Barrier(2), []

    def go():
        c = new_client()
        barrier.wait()
        codes.append(approve(c, "D-1").status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200]
    assert count(db_path, "SELECT COUNT(*) FROM case_file_entries") == 1


def test_approve_not_yet_extracted_returns_409(client):
    deliver(client, "D-1", GOOD)
    assert approve(client, "D-1").status_code == 409


def test_approve_without_claimant_returns_409(client, process_once):
    deliver(client, "D-1", "A letter with no identifiers.")
    process_once()
    assert approve(client, "D-1").status_code == 409


def test_approve_unknown_document_returns_404(client):
    assert approve(client, "nope").status_code == 404


def test_document_ids_with_slashes_can_be_approved(client, process_once):
    deliver(client, "2026/5293", GOOD)
    process_once()
    assert approve(client, "2026/5293").status_code == 200


def test_list_known_tenant_with_no_documents_is_empty(client):
    assert client.get(f"/v1/tenants/{NW}/documents", headers=auth()).json() == []


def test_list_shape_filters_and_pagination(client, process_once):
    deliver(client, "D-1", GOOD)
    deliver(client, "D-2", "A letter with no identifiers.")
    deliver(client, "D-3", GOOD)
    process_once()
    approve(client, "D-3")
    url = f"/v1/tenants/{NW}/documents"
    items = client.get(url, headers=auth()).json()
    assert [i["document_id"] for i in items] == ["D-1", "D-2", "D-3"]
    assert set(items[0]) == {"document_id", "claimant_id", "document_type", "document_date", "needs_review",
                             "review_reasons", "status"}
    review = client.get(url, params={"needs_review": "true"}, headers=auth()).json()
    assert [i["document_id"] for i in review] == ["D-2"]
    filed = client.get(url, params={"status": "filed"}, headers=auth()).json()
    assert [i["document_id"] for i in filed] == ["D-3"]
    page = client.get(url, params={"limit": 1, "offset": 1}, headers=auth()).json()
    assert [i["document_id"] for i in page] == ["D-2"]
    assert client.get(url, params={"status": "bogus"}, headers=auth()).status_code == 400


def test_document_detail_has_audit_trail(client, process_once):
    deliver(client, "D-1", GOOD)
    process_once()
    approve(client, "D-1")
    detail = client.get(f"/v1/tenants/{NW}/documents/D-1", headers=auth()).json()
    assert [e["event"] for e in detail["audit"]] == ["received", "extracted", "filed"]
    assert detail["extractor"] == "rules" and detail["attempts"] == 1


def test_review_page_is_served_with_security_headers(client):
    r = client.get("/review")
    assert r.status_code == 200 and "Review queue" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "localStorage" not in r.text.split("<script>")[1].split("//", 1)[0]  # key is never persisted
