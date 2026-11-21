"""Structured JSON logs with a per-request id, so one delivery can be traced across intake, worker and review."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def configure() -> None:
    root = logging.getLogger("intakeguard")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


def log(logger: logging.Logger, msg: str, **fields) -> None:
    """Log never includes document text or secrets: callers pass ids and outcomes only."""
    logger.info(msg, extra={"fields": fields})
