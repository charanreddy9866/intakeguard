"""Extractor selection. `INTAKEGUARD_EXTRACTOR=rules|anthropic|openai` (default: rules, fully offline)."""
from __future__ import annotations

from intakeguard.config import get_settings
from intakeguard.extractors.base import DOCUMENT_TYPES, Extractor, TransientExtractorError
from intakeguard.extractors.rules import RulesExtractor

__all__ = ["DOCUMENT_TYPES", "Extractor", "TransientExtractorError", "RulesExtractor", "build_extractor"]


def build_extractor(kind: str | None = None) -> Extractor:
    settings = get_settings()
    kind = kind or settings.extractor
    if kind == "rules":
        return RulesExtractor()
    if kind == "anthropic":
        from intakeguard.extractors.llm import AnthropicExtractor
        return AnthropicExtractor(model=settings.llm_model or "claude-haiku-5-5",
                                  timeout=settings.llm_timeout_seconds)
    if kind == "openai":
        from intakeguard.extractors.llm import OpenAICompatibleExtractor
        if not settings.llm_model:
            raise ValueError("set INTAKEGUARD_LLM_MODEL for the openai extractor")
        return OpenAICompatibleExtractor(model=settings.llm_model,
                                         timeout=settings.llm_timeout_seconds)
    raise ValueError(f"unknown extractor: {kind}")
