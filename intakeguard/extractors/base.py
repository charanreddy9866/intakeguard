"""The extractor contract. An extractor sees document text only: never tenant names, claimant lists or secrets."""
from __future__ import annotations

from typing import Any, Protocol

DOCUMENT_TYPES = ("intake_form", "medical_record", "id_document", "other")


class Extractor(Protocol):
    name: str

    def extract(self, text: str) -> Any:
        """Return {"document_type", "claimant_id", "document_date"}. May return garbage or raise."""


class TransientExtractorError(Exception):
    """Raised for errors worth retrying (timeouts, 429, 5xx)."""
