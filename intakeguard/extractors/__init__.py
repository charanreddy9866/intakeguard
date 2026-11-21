"""Extractor selection. `INTAKEGUARD_EXTRACTOR=rules|anthropic|openai|gemini` (default: rules, fully offline)."""
from __future__ import annotations

import os

from intakeguard.config import get_settings
from intakeguard.extractors.base import DOCUMENT_TYPES, Extractor, TransientExtractorError
from intakeguard.extractors.rules import RulesExtractor

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

__all__ = ["DOCUMENT_TYPES", "Extractor", "TransientExtractorError", "RulesExtractor", "build_extractor"]


def build_extractor(kind: str | None = None, model: str | None = None) -> Extractor:
    """`model` overrides INTAKEGUARD_LLM_MODEL (used by evals to compare several models)."""
    settings = get_settings()
    kind = kind or settings.extractor
    llm_model = model or settings.llm_model
    if kind == "rules":
        return RulesExtractor()
    if kind == "anthropic":
        from intakeguard.extractors.llm import AnthropicExtractor
        return AnthropicExtractor(model=llm_model or "claude-haiku-5-5",
                                  timeout=settings.llm_timeout_seconds)
    if kind == "openai":
        from intakeguard.extractors.llm import OpenAICompatibleExtractor
        if not llm_model:
            raise ValueError("set INTAKEGUARD_LLM_MODEL for the openai extractor")
        return OpenAICompatibleExtractor(model=llm_model,
                                         timeout=settings.llm_timeout_seconds)
    if kind == "gemini":
        # Gemini through Google's OpenAI-compatible endpoint, keyed by GEMINI_API_KEY.
        from intakeguard.extractors.llm import OpenAICompatibleExtractor
        if not llm_model:
            raise ValueError("set INTAKEGUARD_LLM_MODEL (or --model) for the gemini extractor")
        extractor = OpenAICompatibleExtractor(
            model=llm_model, api_key=os.environ.get("GEMINI_API_KEY", ""),
            base_url=os.environ.get("GEMINI_BASE_URL", GEMINI_OPENAI_BASE_URL),
            timeout=settings.llm_timeout_seconds,
        )
        extractor.name = "gemini"
        return extractor
    raise ValueError(f"unknown extractor: {kind}")
