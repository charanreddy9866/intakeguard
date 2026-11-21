"""Validate every extractor answer in code. The model proposes; this module decides what is stored.

Rules:
- invalid answer (not a dict, missing key, wrong type, unknown document_type, impossible date, claimant not in this
  tenant, extractor error) -> all three fields null, needs_review true, with machine-readable reasons
- valid answer with no claimant -> fields kept, needs_review true ("no_claimant")
- text that looks like a prompt-injection attempt -> fields kept if valid, needs_review true
  ("possible_prompt_injection"), so a human always looks at it
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from intakeguard.extractors.base import DOCUMENT_TYPES

_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INJECTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|your\s+|the\s+)*(?:previous\s+|prior\s+|above\s+)?instructions"
    r"|disregard\s+(?:all\s+|the\s+|your\s+)*(?:previous\s+|prior\s+|above\s+)?(?:instructions|rules)"
    r"|\b(?:system|assistant)\s*(?:prompt|note|message)\s*:"
    r"|you\s+are\s+now\b|mark\s+(?:this|it)\s+as\s+(?:approved|reviewed|filed)",
    re.I,
)
FIELDS = ("document_type", "claimant_id", "document_date")


@dataclass
class CheckedExtraction:
    document_type: str | None
    claimant_id: str | None
    document_date: str | None
    needs_review: bool
    reasons: list[str] = field(default_factory=list)
    injection_suspected: bool = False

    def fields(self) -> dict:
        return {f: getattr(self, f) for f in FIELDS}


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def check(raw: Any, valid_claimant_ids: set[str]) -> CheckedExtraction:
    problem = _problem(raw, valid_claimant_ids)
    if problem:
        return CheckedExtraction(None, None, None, needs_review=True, reasons=[problem])
    result = CheckedExtraction(raw["document_type"], raw["claimant_id"], raw["document_date"], needs_review=False)
    if result.claimant_id is None:
        result.needs_review = True
        result.reasons.append("no_claimant")
    return result


def extract_and_check(
    text: str,
    valid_claimant_ids: set[str],
    extract: Callable[[str], Any],
) -> CheckedExtraction:
    """The single path used by the worker AND the evals, so evals measure exactly what production stores.

    `extract` receives the text and nothing else.
    """
    try:
        raw = extract(text)
    except Exception as exc:  # noqa: BLE001 - any extractor failure becomes a reviewable result, never a crash
        reason = f"extractor_error:{type(exc).__name__}"
        result = CheckedExtraction(None, None, None, needs_review=True, reasons=[reason])
    else:
        result = check(raw, valid_claimant_ids)
    if looks_like_injection(text):
        result.injection_suspected = True
        result.needs_review = True
        result.reasons.append("possible_prompt_injection")
    return result


def _problem(raw: Any, valid_claimant_ids: set[str]) -> str | None:
    if not isinstance(raw, dict):
        return "not_an_object"
    for key in FIELDS:
        if key not in raw:
            return f"missing_key:{key}"
    doc_type, claimant, date = raw["document_type"], raw["claimant_id"], raw["document_date"]
    if not isinstance(doc_type, str) or doc_type not in DOCUMENT_TYPES:
        return "unknown_document_type"
    if claimant is not None and not isinstance(claimant, str):
        return "claimant_wrong_type"
    if isinstance(claimant, str) and claimant not in valid_claimant_ids:
        return "claimant_not_in_tenant"
    if date is not None:
        if not isinstance(date, str) or not _DATE_SHAPE.match(date):
            return "date_wrong_format"
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            return "date_not_a_calendar_date"
    return None
