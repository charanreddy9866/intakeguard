"""Deterministic, offline extractor. The default, the CI baseline, and the fallback when no LLM is configured."""
from __future__ import annotations

import re

_TYPE_PATTERNS = [
    ("intake_form", re.compile(r"\bintake\s+form\b", re.I)),
    ("medical_record", re.compile(r"\bmedical\s+record\b|\bdischarge\s+summary\b", re.I)),
    ("id_document", re.compile(r"\b(?:id|identity)\s+document\b|\bpassport\b|\bdriver'?s\s+licen[cs]e\b", re.I)),
]
_CLAIMANT = re.compile(r"claimant\s+id\s*[:#]?\s*(C-\d+)", re.I)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


class RulesExtractor:
    name = "rules"

    def extract(self, text: str) -> dict:
        return {
            "document_type": _document_type(text),
            "claimant_id": _first(_CLAIMANT, text, upper=True),
            "document_date": _first(_DATE, text),
        }


def _document_type(text: str) -> str:
    """The type whose phrase appears EARLIEST in the text (not the first pattern in the list)."""
    best: tuple[int, str] | None = None
    for doc_type, pattern in _TYPE_PATTERNS:
        m = pattern.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), doc_type)
    return best[1] if best else "other"


def _first(pattern: re.Pattern, text: str, upper: bool = False) -> str | None:
    m = pattern.search(text)
    if not m:
        return None
    return m.group(1).upper() if upper else m.group(1)
