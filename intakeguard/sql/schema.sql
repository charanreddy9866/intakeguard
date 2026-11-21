-- IntakeGuard schema. Idempotent. Every table that holds tenant data is keyed by tenant.
CREATE TABLE IF NOT EXISTS tenants (
    tenant          TEXT PRIMARY KEY,
    inbox           TEXT NOT NULL UNIQUE,
    webhook_secret  TEXT NOT NULL,
    api_key_sha256  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS claimants (
    tenant       TEXT NOT NULL REFERENCES tenants(tenant),
    claimant_id  TEXT NOT NULL,
    PRIMARY KEY (tenant, claimant_id)
);

CREATE TABLE IF NOT EXISTS documents (
    tenant               TEXT NOT NULL REFERENCES tenants(tenant),
    document_id          TEXT NOT NULL,
    text                 TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'received'
                         CHECK (status IN ('received', 'processing', 'pending', 'filed')),
    document_type        TEXT CHECK (document_type IS NULL OR
                         document_type IN ('intake_form', 'medical_record', 'id_document', 'other')),
    claimant_id          TEXT,
    document_date        TEXT,
    needs_review         INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
    review_reasons       TEXT NOT NULL DEFAULT '[]',
    injection_suspected  INTEGER NOT NULL DEFAULT 0 CHECK (injection_suspected IN (0, 1)),
    extractor            TEXT,
    attempts             INTEGER NOT NULL DEFAULT 0,
    lease_owner          TEXT,
    lease_expires_at     REAL,
    received_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (tenant, document_id),
    FOREIGN KEY (tenant, claimant_id) REFERENCES claimants(tenant, claimant_id)
);

CREATE TABLE IF NOT EXISTS case_file_entries (
    tenant       TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    claimant_id  TEXT NOT NULL,
    approved_by  TEXT NOT NULL,
    filed_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (tenant, document_id),
    FOREIGN KEY (tenant, document_id) REFERENCES documents(tenant, document_id),
    FOREIGN KEY (tenant, claimant_id) REFERENCES claimants(tenant, claimant_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant       TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    event        TEXT NOT NULL,
    actor        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '{}',
    at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS documents_status ON documents(status, lease_expires_at);
CREATE INDEX IF NOT EXISTS audit_document ON audit_log(tenant, document_id);
