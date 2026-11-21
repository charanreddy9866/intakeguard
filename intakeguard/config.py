"""Runtime settings, read from environment variables once per call (cheap, and test-friendly)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    signature_tolerance_seconds: int
    lease_seconds: float
    max_attempts: int
    extractor: str
    llm_model: str | None
    llm_timeout_seconds: float
    llm_retries: int
    demo: bool


def get_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("INTAKEGUARD_DB") or "./intakeguard.db",
        signature_tolerance_seconds=int(os.environ.get("INTAKEGUARD_SIGNATURE_TOLERANCE", "300")),
        lease_seconds=float(os.environ.get("INTAKEGUARD_LEASE_SECONDS", "60")),
        max_attempts=int(os.environ.get("INTAKEGUARD_MAX_ATTEMPTS", "3")),
        extractor=os.environ.get("INTAKEGUARD_EXTRACTOR", "rules"),
        llm_model=os.environ.get("INTAKEGUARD_LLM_MODEL") or None,
        llm_timeout_seconds=float(os.environ.get("INTAKEGUARD_LLM_TIMEOUT", "30")),
        llm_retries=int(os.environ.get("INTAKEGUARD_LLM_RETRIES", "2")),
        demo=os.environ.get("INTAKEGUARD_DEMO", "").lower() in ("1", "true", "yes"),
    )
