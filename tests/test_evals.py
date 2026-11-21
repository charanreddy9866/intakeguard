import json

import httpx
import pytest

from evals.__main__ import DATASETS, GATED, load, run
from evals.compare import RunSpec, cost_per_1k_docs, parse_spec, table
from intakeguard.extractors.base import DOCUMENT_TYPES
from intakeguard.extractors.llm import AnthropicExtractor


@pytest.mark.parametrize("name", list(DATASETS))
def test_datasets_are_well_formed(name):
    rows = load(name)
    assert len(rows) == 30
    assert len({r["id"] for r in rows}) == 30
    for r in rows:
        assert r["tenant"] in {"northwind-legal", "harbor-claims"}
        assert set(r["expected"]) == set(GATED)
        assert r["expected"]["document_type"] in (*DOCUMENT_TYPES, None)
        assert r["tags"], r["id"]


def test_hard_set_is_actually_hard_for_the_rules_baseline():
    report = run(load("hard"), "rules")
    assert min(report["accuracy"].values()) < 0.90


def test_run_reports_llm_usage_from_a_mocked_provider():
    def handler(request):
        text = json.loads(request.content)["messages"][0]["content"]
        claimant = "C-101" if "C-101" in text else None
        return httpx.Response(200, json={
            "content": [{"type": "tool_use", "input": {"document_type": "other", "claimant_id": claimant,
                                                        "document_date": None}}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        })
    ext = AnthropicExtractor("mock-model", api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    report = run(load("core"), "anthropic", extractor=ext)
    assert report["model"] == "mock-model"
    assert report["usage"] == {"calls": 30, "input_tokens": 3000, "output_tokens": 600}


def test_parse_spec_and_cost():
    spec = parse_spec("anthropic:claude-x@1/5")
    assert spec == RunSpec("anthropic", "claude-x", 1.0, 5.0)
    report = {"documents": 10, "usage": {"input_tokens": 1000, "output_tokens": 200}}
    # (1000*1 + 200*5) / 1e6 USD for 10 docs -> $0.20 per 1k docs
    assert cost_per_1k_docs(report, spec) == "$0.20"
    assert cost_per_1k_docs(report, parse_spec("openai:m")) == "n/a"
    assert cost_per_1k_docs(report, parse_spec("rules")) == "$0"
    with pytest.raises(ValueError):
        parse_spec("bogus")


def test_table_renders_one_row_per_run():
    report = run(load("core"), "rules")
    md = table([(parse_spec("rules"), "core", report)])
    assert md.count("\n") == 2 and "`rules` | core | 100%" in md and "| 0/30 |" in md


def test_extractor_errors_are_counted_and_delay_is_applied():
    slept = []

    def failing(_text):
        raise RuntimeError("429")

    class Fake:
        name, model, usage = "fake", None, None
        extract = staticmethod(failing)

    report = run(load("core"), "fake", extractor=Fake(), delay=2.0, sleep=slept.append)
    assert report["extractor_errors"] == 30
    assert slept == [2.0] * 29
