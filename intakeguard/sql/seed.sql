-- Synthetic demo data. Secrets and API keys are public test fixtures; never reuse them.
-- API keys (plaintext, for the demo only): northwind-legal -> nw-demo-api-key, harbor-claims -> hc-demo-api-key
INSERT OR IGNORE INTO tenants (tenant, inbox, webhook_secret, api_key_sha256) VALUES
    ('northwind-legal', 'intake@northwind-legal.example', 'northwind-demo-secret',
     '8cded0d74f1f47d245c0458f50349573c0f9a16e5eb59d5a5ee316f28db17a95'),
    ('harbor-claims',   'intake@harbor-claims.example',   'harbor-demo-secret',
     'fefcbcd7c0513b9052639d80db740247e087156a05fbc42140d3ec02eb3c85fe');

-- C-101 exists in BOTH tenants and is a different person in each.
INSERT OR IGNORE INTO claimants (tenant, claimant_id) VALUES
    ('northwind-legal', 'C-101'),
    ('northwind-legal', 'C-102'),
    ('harbor-claims',   'C-101'),
    ('harbor-claims',   'C-205');
