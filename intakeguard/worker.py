"""Extraction worker: `python -m intakeguard.worker --once` (or `--loop`).

Concurrency and recovery:
- A worker claims a document with one conditional UPDATE that sets a lease (owner + expiry). Only the worker whose
  UPDATE changed the row calls the extractor, so two workers never extract the same document at the same time.
- If a worker dies mid-document, its lease expires and another worker reclaims the row. After `max_attempts`
  claims the document is parked for human review instead of looping forever.
- The result is written only while the lease is still ours (fencing), so a slow worker whose lease was taken over
  cannot overwrite the newer result.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from typing import Any

from intakeguard import db, metrics
from intakeguard.config import get_settings
from intakeguard.extractors import Extractor, TransientExtractorError, build_extractor
from intakeguard.guardrails import CheckedExtraction, extract_and_check
from intakeguard.logging_setup import configure, log

logger = logging.getLogger("intakeguard.worker")

_CANDIDATES = (
    "SELECT tenant, document_id FROM documents "
    "WHERE status = 'received' OR (status = 'processing' AND lease_expires_at < ?) "
    "ORDER BY received_at, tenant, document_id"
)
_CLAIM = (
    "UPDATE documents SET status = 'processing', lease_owner = :wid, lease_expires_at = :expires, "
    "attempts = attempts + 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
    "WHERE tenant = :t AND document_id = :d "
    "AND (status = 'received' OR (status = 'processing' AND lease_expires_at < :now))"
)
_WRITE = (
    "UPDATE documents SET document_type = :document_type, claimant_id = :claimant_id, "
    "document_date = :document_date, needs_review = :needs_review, review_reasons = :reasons, "
    "injection_suspected = :injection, extractor = :extractor, status = 'pending', lease_owner = NULL, "
    "lease_expires_at = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
    "WHERE tenant = :t AND document_id = :d AND status = 'processing' AND lease_owner = :wid"
)


def with_retries(extract: Callable[[str], Any], retries: int, sleep: Callable[[float], None] = time.sleep,
                 base_delay: float = 0.5) -> Callable[[str], Any]:
    """Retry transient extractor errors with exponential backoff; other errors are raised at once."""
    def call(text: str) -> Any:
        for attempt in range(retries + 1):
            try:
                return extract(text)
            except TransientExtractorError:
                if attempt == retries:
                    raise
                sleep(base_delay * (2 ** attempt))
        raise RuntimeError("unreachable")
    return call


def process_once(
    db_path: str | None = None,
    extractor: Extractor | Callable[[str], Any] | None = None,
    worker_id: str | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Process every claimable document once. Returns how many documents this call moved to `pending`."""
    settings = get_settings()
    worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}"
    extractor = extractor or build_extractor()
    extract_fn = extractor.extract if hasattr(extractor, "extract") else extractor
    extractor_name = getattr(extractor, "name", getattr(extractor, "__name__", "custom"))
    extract_fn = with_retries(extract_fn, settings.llm_retries, sleep=sleep)

    processed = 0
    with closing(db.connect(db_path)) as conn:
        db.init_db(conn)
        for row in conn.execute(_CANDIDATES, (now(),)).fetchall():
            tenant, document_id = row["tenant"], row["document_id"]
            t = now()
            claim = conn.execute(_CLAIM, {"wid": worker_id, "expires": t + settings.lease_seconds,
                                          "t": tenant, "d": document_id, "now": t})
            if claim.rowcount != 1:
                continue  # another worker owns it
            doc = conn.execute("SELECT text, attempts FROM documents WHERE tenant = ? AND document_id = ?",
                               (tenant, document_id)).fetchone()
            if doc["attempts"] > settings.max_attempts:
                result = CheckedExtraction(None, None, None, needs_review=True, reasons=["max_attempts_exceeded"])
            else:
                # The extractor receives the document text and nothing else.
                result = extract_and_check(doc["text"], db.valid_claimant_ids(conn, tenant), extract_fn)
            processed += _write(conn, tenant, document_id, worker_id, extractor_name, result)
    return processed


def _write(conn, tenant: str, document_id: str, worker_id: str, extractor_name: str,
           result: CheckedExtraction) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(_WRITE, {
            **result.fields(),
            "needs_review": int(result.needs_review),
            "reasons": json.dumps(result.reasons),
            "injection": int(result.injection_suspected),
            "extractor": extractor_name,
            "t": tenant, "d": document_id, "wid": worker_id,
        })
        if cur.rowcount == 1:
            db.audit(conn, tenant, document_id, "extracted", worker_id, extractor=extractor_name,
                     needs_review=result.needs_review, reasons=result.reasons)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if cur.rowcount == 1:
        outcome = "review" if result.needs_review else "auto_ready"
        metrics.inc("extractions_total", outcome=outcome, extractor=extractor_name)
        log(logger, "document extracted", tenant=tenant, document_id=document_id, outcome=outcome,
            reasons=result.reasons)
    else:
        log(logger, "lease lost before write; result discarded", tenant=tenant, document_id=document_id)
    return cur.rowcount


def main(argv: list[str] | None = None) -> int:
    configure()
    parser = argparse.ArgumentParser(prog="python -m intakeguard.worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="process every claimable document, then exit")
    mode.add_argument("--loop", action="store_true", help="keep polling")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between polls with --loop")
    args = parser.parse_args(argv)
    if args.once:
        print(f"processed {process_once()} document(s)")
        return 0
    while True:  # pragma: no cover - exercised manually
        process_once()
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
