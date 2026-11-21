"""HTTP API: signed intake webhook, authenticated review routes, health and metrics."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from contextlib import closing

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse

from intakeguard import db, metrics
from intakeguard.config import get_settings
from intakeguard.logging_setup import configure, log, request_id
from intakeguard.security import hash_api_key, verify_signature

logger = logging.getLogger("intakeguard.api")

MAX_BODY_BYTES = 1_000_000
DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
STATUSES = {"received", "processing", "pending", "filed"}


def create_app(db_path: str | None = None) -> FastAPI:
    configure()
    path = db_path or get_settings().db_path
    with closing(db.connect(path)) as conn:
        db.init_db(conn)

    app = FastAPI(title="IntakeGuard", version="1.0.0",
                  description="Multi-tenant document intake with guarded AI extraction and human approval.")

    def open_db() -> sqlite3.Connection:
        return db.connect(path)

    @app.middleware("http")
    async def with_request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["x-request-id"] = rid
        return response

    # ---------- intake ----------

    @app.post("/v1/webhooks/documents")
    async def receive_document(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, "body too large")
        payload = _parse_payload(raw)  # 400 before anything else
        timestamp = request.headers.get("x-timestamp")
        signature = request.headers.get("x-signature")
        tolerance = get_settings().signature_tolerance_seconds
        return await run_in_threadpool(_store, payload, raw, timestamp, signature, tolerance)

    def _store(payload: dict, raw: bytes, timestamp, signature, tolerance):
        with closing(open_db()) as conn:
            tenant_row = conn.execute(
                "SELECT tenant, webhook_secret FROM tenants WHERE inbox = ?", (payload["inbox"],)
            ).fetchone()
            if tenant_row is None:
                metrics.inc("webhook_rejected_total", reason="unknown_inbox")
                raise HTTPException(404, "unknown inbox")
            reason = verify_signature(tenant_row["webhook_secret"], timestamp, signature, raw, tolerance)
            if reason:
                metrics.inc("webhook_rejected_total", reason=reason)
                log(logger, "webhook rejected", tenant=tenant_row["tenant"], reason=reason)
                raise HTTPException(403, reason)
            tenant = tenant_row["tenant"]
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    "INSERT INTO documents (tenant, document_id, text) VALUES (?, ?, ?) "
                    "ON CONFLICT(tenant, document_id) DO NOTHING",
                    (tenant, payload["document_id"], payload["text"]),
                )
                created = cur.rowcount == 1
                if created:
                    db.audit(conn, tenant, payload["document_id"], "received", "vendor")
                status = conn.execute(
                    "SELECT status FROM documents WHERE tenant = ? AND document_id = ?",
                    (tenant, payload["document_id"]),
                ).fetchone()["status"]
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        metrics.inc("webhook_accepted_total", duplicate=str(not created).lower())
        log(logger, "document received", tenant=tenant, document_id=payload["document_id"], duplicate=not created)
        return {"document_id": payload["document_id"], "status": status, "duplicate": not created}

    # ---------- review (authenticated per tenant) ----------

    def require_tenant(tenant: str, authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        key_hash = hash_api_key(authorization[7:].strip())
        with closing(open_db()) as conn:
            row = conn.execute("SELECT tenant FROM tenants WHERE api_key_sha256 = ?", (key_hash,)).fetchone()
        if row is None:
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
        if row["tenant"] != tenant:
            raise HTTPException(404, "unknown tenant")  # never confirm that another tenant exists
        return tenant

    @app.post("/v1/tenants/{tenant}/documents/{document_id:path}/approve")
    def approve(document_id: str, tenant: str = Depends(require_tenant)):
        with closing(open_db()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                doc = conn.execute(
                    "SELECT claimant_id, status FROM documents WHERE tenant = ? AND document_id = ?",
                    (tenant, document_id),
                ).fetchone()
                if doc is None:
                    raise HTTPException(404, "unknown document")
                if doc["claimant_id"] is None or doc["status"] not in ("pending", "filed"):
                    raise HTTPException(409, "document has no confirmed claimant")
                cur = conn.execute(
                    "INSERT OR IGNORE INTO case_file_entries (tenant, document_id, claimant_id, approved_by) "
                    "VALUES (?, ?, ?, ?)",
                    (tenant, document_id, doc["claimant_id"], f"api-key:{tenant}"),
                )
                if cur.rowcount == 1:
                    conn.execute(
                        "UPDATE documents SET status='filed', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                        "WHERE tenant = ? AND document_id = ?",
                        (tenant, document_id),
                    )
                    db.audit(conn, tenant, document_id, "filed", f"api-key:{tenant}", claimant_id=doc["claimant_id"])
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        metrics.inc("approvals_total", first=str(cur.rowcount == 1).lower())
        return {"document_id": document_id, "claimant_id": doc["claimant_id"], "status": "filed"}

    @app.get("/v1/tenants/{tenant}/documents")
    def list_documents(
        tenant: str = Depends(require_tenant),
        status: str | None = Query(default=None),
        needs_review: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        if status is not None and status not in STATUSES:
            raise HTTPException(400, "unknown status")
        sql = ("SELECT document_id, claimant_id, document_type, document_date, needs_review, status, "
               "review_reasons FROM documents WHERE tenant = ?")
        args: list = [tenant]
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        if needs_review is not None:
            sql += " AND needs_review = ?"
            args.append(int(needs_review))
        sql += " ORDER BY document_id LIMIT ? OFFSET ?"
        args += [limit, offset]
        with closing(open_db()) as conn:
            return [_document_out(r) for r in conn.execute(sql, args)]

    @app.get("/v1/tenants/{tenant}/documents/{document_id:path}")
    def get_document(document_id: str, tenant: str = Depends(require_tenant)):
        with closing(open_db()) as conn:
            row = conn.execute(
                "SELECT document_id, claimant_id, document_type, document_date, needs_review, status, "
                "review_reasons, injection_suspected, extractor, attempts FROM documents "
                "WHERE tenant = ? AND document_id = ?",
                (tenant, document_id),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "unknown document")
            trail = conn.execute(
                "SELECT event, actor, detail, at FROM audit_log WHERE tenant = ? AND document_id = ? ORDER BY id",
                (tenant, document_id),
            ).fetchall()
        out = _document_out(row)
        out.update(injection_suspected=bool(row["injection_suspected"]), extractor=row["extractor"],
                   attempts=row["attempts"],
                   audit=[{"event": t["event"], "actor": t["actor"], "detail": json.loads(t["detail"]),
                           "at": t["at"]} for t in trail])
        return out

    # ---------- ops ----------

    @app.get("/healthz")
    def healthz():
        with closing(open_db()) as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics_endpoint():
        with closing(open_db()) as conn:
            return metrics.render(conn)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    return app


def _parse_payload(raw: bytes) -> dict:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "body must be a JSON object")
    for field in ("document_id", "inbox", "text"):
        if not isinstance(payload.get(field), str):
            raise HTTPException(400, f"missing or non-string field: {field}")
        try:
            payload[field].encode("utf-8")  # rejects lone surrogates, which SQLite cannot store
        except UnicodeEncodeError:
            raise HTTPException(400, f"invalid characters in {field}") from None
    if not DOCUMENT_ID.match(payload["document_id"]):
        raise HTTPException(400, "document_id must match [A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
    return payload


def _document_out(row: sqlite3.Row) -> dict:
    return {
        "document_id": row["document_id"],
        "claimant_id": row["claimant_id"],
        "document_type": row["document_type"],
        "document_date": row["document_date"],
        "needs_review": bool(row["needs_review"]),
        "review_reasons": json.loads(row["review_reasons"]),
        "status": row["status"],
    }

