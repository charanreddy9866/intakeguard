from evals.__main__ import load, run
from tests.conftest import NW, auth, deliver


def test_end_to_end_webhook_worker_approve_list(client, process_once):
    assert deliver(client, "D-1", "Intake form. Claimant ID: C-101. Signed 2026-10-27.").status_code == 200
    assert process_once() == 1
    assert client.post(f"/v1/tenants/{NW}/documents/D-1/approve", headers=auth()).status_code == 200
    assert client.get(f"/v1/tenants/{NW}/documents", headers=auth()).json() == [{
        "document_id": "D-1", "claimant_id": "C-101", "document_type": "intake_form",
        "document_date": "2026-10-27", "needs_review": False, "review_reasons": [], "status": "filed",
    }]
    text = client.get("/metrics").text
    assert 'intakeguard_documents{tenant="northwind-legal",status="filed"} 1' in text
    assert "intakeguard_approvals_total" in text


def test_evals_pass_the_gate_with_the_rules_extractor():
    report = run(load(), "rules")
    assert report["documents"] == 30
    assert all(acc >= 0.90 for acc in report["accuracy"].values()), report["misses"]
