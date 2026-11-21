# IntakeGuard

[![ci](https://github.com/charanreddy9866/intakeguard/actions/workflows/ci.yml/badge.svg)](https://github.com/charanreddy9866/intakeguard/actions/workflows/ci.yml)

**Multi-tenant document intake with guarded LLM extraction, evals as a CI gate, and human-in-the-loop approval.**

Scanned mail arrives from a vendor as text through a signed webhook. A worker asks an extractor (a deterministic
rules engine, Claude, or any OpenAI-compatible model) what each document is and whose it is. Code validates every
answer, flags anything doubtful, and a person approves before a document is filed to a claimant's case file.

The goal of the project is to show how to put an LLM into a workflow where a wrong answer has a cost (legal,
insurance and healthcare intake), without trusting the model.

```
vendor ──signed webhook──▶ API ──▶ SQLite ◀── worker(s) ──text only──▶ extractor (rules | Claude | OpenAI)
                                      ▲                                     │
staff ──API key──▶ review queue ──────┘          guardrails ◀──proposal─────┘
            approve ──▶ case file + audit log
```

## What it demonstrates

| Area | How |
|---|---|
| **LLM integration** | Anthropic Messages API with a forced tool call (structured output) and OpenAI-compatible JSON mode, over plain `httpx`. Temperature 0, timeouts, retries with exponential backoff on 429/5xx only. |
| **Guardrails** | The model only proposes. `guardrails.py` validates types, enum values, real calendar dates, and that the claimant belongs to *this* tenant (catches hallucinated IDs). Invalid answers are nulled and sent to review with machine-readable reasons. |
| **Prompt-injection defence in depth** | The extractor sees document text only, never tenant data or secrets. Text is fenced in `<document>` tags with a closing-tag escape neutralised; the system prompt says the content is data. A detector flags injection-like text for mandatory human review. Nothing is filed without approval. |
| **Evals as a release gate** | 30 labelled documents tagged by scenario (wrong-tenant claimant, impossible dates, leap days, injections, ambiguous types). `python -m evals` runs the same code path the worker uses, reports per-field accuracy, per-tag results and latency, and fails CI below 90%. The same set can score an LLM provider: `python -m evals --extractor anthropic`. |
| **Human in the loop** | Review queue (`needs_review=true`) with reasons, idempotent approval, full audit trail per document. |
| **Reliability** | Lease-based work claiming (two workers never extract the same document; a crashed worker's lease expires and is reclaimed), fencing so a stale worker can't overwrite, poison documents parked after N attempts, idempotent intake and approval enforced by primary keys rather than racy checks. |
| **Security** | HMAC-SHA256 webhooks with a timestamp bound into the MAC (replay protection), constant-time comparison, per-tenant API keys stored as hashes, cross-tenant requests answered as 404, body size limit, strict ID format. |
| **Multi-tenancy** | Tenant is part of every key. `C-101` exists in both demo tenants as two different people, and tests prove they never mix. |
| **Observability** | Structured JSON logs with a request id (never document text or secrets), Prometheus-style `/metrics` with status gauges and review-queue depth, `/healthz`. |
| **Test quality** | 90 tests including concurrency races run five times each. `scripts/mutation_check.py` removes each protection in a scratch copy and proves a test fails: **8/8 caught**. |
| **Agentic engineering** | `CLAUDE.md`/`AGENTS.md`, a written contract, and a Claude Code `PreToolUse` hook that gives each agent role a write scope and keeps the extractor author and the eval author from seeing each other's files. |
| **Delivery** | GitHub Actions on Python 3.11–3.13 (lint, tests, eval gate, mutation check), eval report as a build artifact, non-root Docker image with a health check and a container smoke test. |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest -q                  # 90 tests
python -m evals                      # eval gate
python scripts/mutation_check.py     # prove the tests guard each protection

uvicorn intakeguard.api:create_app --factory --port 8000 &
scripts/demo.sh                      # deliver 3 docs, run the worker, review queue, approve, audit, metrics
```

Docker:

```bash
docker build -t intakeguard . && docker run -p 8000:8000 intakeguard
```

Use a real model (optional; everything works offline with the rules extractor):

```bash
export INTAKEGUARD_EXTRACTOR=anthropic ANTHROPIC_API_KEY=...        # default model: claude-haiku-5-5
export INTAKEGUARD_EXTRACTOR=openai OPENAI_API_KEY=... INTAKEGUARD_LLM_MODEL=<model>   # OPENAI_BASE_URL for compatible APIs
python -m evals --extractor anthropic   # compare a provider against the same labelled set
```

## Demo output

```
== review queue (needs_review=true)
[{"document_id":"DEMO-2","claimant_id":null,"document_type":"other","needs_review":true,
  "review_reasons":["no_claimant"],"status":"pending"},
 {"document_id":"DEMO-3","claimant_id":"C-102","document_type":"medical_record","needs_review":true,
  "review_reasons":["possible_prompt_injection"],"status":"pending"}]
== approve the clean document
{"document_id":"DEMO-1","claimant_id":"C-101","status":"filed"}
== audit trail: received (vendor) -> extracted (worker w-9217d125, rules) -> filed (api-key:northwind-legal)
```

```
$ python scripts/mutation_check.py
CAUGHT  signature check bypassed                      6 failed, 22 deselected
CAUGHT  ON CONFLICT removed                           6 failed, 22 deselected
CAUGHT  claim condition removed                       5 failed, 21 deselected
CAUGHT  tenant filter removed from worker text lookup 1 failed, 25 deselected
CAUGHT  lease fencing removed                         1 failed, 25 deselected
CAUGHT  cross-tenant key check removed                1 failed, 10 deselected
CAUGHT  calendar-date check removed                   1 failed, 7 passed, 18 deselected
CAUGHT  case-file idempotency removed                 1 failed, 13 deselected
8/8 protections are guarded by a failing test
```

## API

| Route | Auth | |
|---|---|---|
| `POST /v1/webhooks/documents` | HMAC (`X-Timestamp`, `X-Signature`) | 400 / 404 / 403 / 413 / 200; idempotent per `(tenant, document_id)` |
| `GET /v1/tenants/{tenant}/documents?status=&needs_review=&limit=&offset=` | `Bearer` tenant key | review queue and listing |
| `GET /v1/tenants/{tenant}/documents/{id}` | `Bearer` tenant key | fields, review reasons, audit trail |
| `POST /v1/tenants/{tenant}/documents/{id}/approve` | `Bearer` tenant key | 409 without a confirmed claimant; idempotent |
| `GET /healthz`, `GET /metrics` | — | ops |

Interactive docs at `/docs`. The full contract (schema, status machine, guardrail table, error rules) is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Demo credentials are in `intakeguard/sql/seed.sql`; they are public
fixtures, so never reuse them.

## Project layout

```
intakeguard/
  api.py            FastAPI app: webhook, review routes, health, metrics
  worker.py         lease-based extraction worker (python -m intakeguard.worker --once | --loop)
  guardrails.py     validation of every model answer + injection flag (shared by worker and evals)
  extractors/       rules.py (offline), llm.py (Anthropic + OpenAI-compatible), base.py (protocol)
  security.py       HMAC signatures with replay window, API-key hashing
  db.py, sql/       SQLite connection, schema, synthetic seed
  metrics.py, logging_setup.py
evals/              dataset.jsonl (30 tagged documents) + runner
tests/              90 tests: webhook, auth, worker races and recovery, review API, LLM adapters, end to end
scripts/            demo.sh, mutation_check.py
.claude/            settings.json (permissions) + hooks/guard.py + roles.json (multi-agent scopes)
```

## Design decisions

- **Code decides, the model proposes.** Every field the model returns is checked against the database for this
  tenant. A model that invents `C-999` or a 30th of February gets nulled and queued, not filed.
- **The database enforces idempotency.** A primary key with `ON CONFLICT DO NOTHING` (intake) and
  `INSERT OR IGNORE` (approval) cannot race; "check, then insert" can.
- **Leases instead of locks.** A conditional `UPDATE` claims a row with an expiry. That gives exactly one active
  extractor per document, recovery after a crash, and a fence against a worker that comes back late.
- **One code path for evals and production.** The eval runner calls `extract_and_check`, the same function the
  worker calls, so the eval measures what would actually be stored.
- **Offline by default.** The rules extractor keeps CI deterministic and free; LLM adapters are tested against
  `httpx.MockTransport`, so tests never need keys or network.

## Limitations and next steps

- **Eval honesty:** the rules extractor scores 100% because its rules and the labels were written by the same
  author against the same conventions. The set's real value is comparing LLM providers and catching regressions;
  it needs messier, independently labelled documents to measure robustness.
- **SQLite has one writer.** Fine for a demo and modest load; under bursty vendor retries it becomes the
  bottleneck. Next: Postgres (`SELECT ... FOR UPDATE SKIP LOCKED` for claiming) and a queue between intake and
  extraction.
- **Counters are per process.** `/metrics` counters come from the API process; the worker's counters are logged,
  and the DB gauges (status counts, review depth) are the source of truth. Next: OpenTelemetry traces and metrics.
- **Injection detection is a heuristic** that triggers review; it is not a classifier and does not block anything
  by itself. The real protections are text-only input, validation in code, and human approval.
- No key rotation, rate limiting or per-user identities for reviewers yet.

## Development workflow

Built with AI coding agents (Claude Code) under the guarded workflow in `CLAUDE.md` and `.claude/`: a written
contract first, one scoped role per agent, a hook that enforces each role's boundaries, and CI that re-checks
lint, tests, the eval gate and the mutation check on every push.

## License

MIT
