"""`python -m evals`: score the production extract-and-check path against a labelled dataset.

    python -m evals                         # rules extractor, offline (what CI runs)
    python -m evals --extractor anthropic   # same dataset against an LLM (needs ANTHROPIC_API_KEY)
    python -m evals --dataset hard          # the messier set (OCR noise, synonyms, natural-language dates)
    python -m evals --report evals/report.json

Exits 1 if any gated field is below --threshold, so a regression fails the build.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from intakeguard import db
from intakeguard.extractors import build_extractor
from intakeguard.guardrails import extract_and_check
from intakeguard.worker import with_retries

HERE = Path(__file__).resolve().parent
DATASETS = {"core": HERE / "dataset.jsonl", "hard": HERE / "dataset_hard.jsonl"}
DATASET = DATASETS["core"]
GATED = ("document_type", "claimant_id", "document_date", "needs_review")


def load(path: Path | str = DATASET) -> list[dict]:
    path = DATASETS.get(str(path), Path(path))
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def run(rows: list[dict], extractor_kind: str = "rules", model: str | None = None, extractor=None) -> dict:
    extractor = extractor or build_extractor(extractor_kind, model)
    extract = with_retries(extractor.extract, retries=2)
    with closing(db.connect(":memory:")) as conn:
        db.init_db(conn)
        claimants = {t: db.valid_claimant_ids(conn, t) for t in {r["tenant"] for r in rows}}

    correct: dict[str, int] = defaultdict(int)
    by_tag: dict[str, list[bool]] = defaultdict(list)
    misses, latencies = [], []
    for row in rows:
        start = time.perf_counter()
        result = extract_and_check(row["text"], claimants[row["tenant"]], extract)
        latencies.append(time.perf_counter() - start)
        got = {**result.fields(), "needs_review": result.needs_review}
        all_ok = True
        for field in GATED:
            ok = got[field] == row["expected"][field]
            correct[field] += ok
            all_ok &= ok
            if not ok:
                misses.append({"id": row["id"], "field": field, "expected": row["expected"][field],
                               "got": got[field], "reasons": result.reasons})
        for tag in row.get("tags", []):
            by_tag[tag].append(all_ok)

    n = len(rows)
    latencies.sort()
    usage = dict(getattr(extractor, "usage", None) or {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    return {
        "extractor": extractor_kind,
        "model": getattr(extractor, "model", None),
        "usage": usage,
        "documents": n,
        "accuracy": {f: round(correct[f] / n, 4) for f in GATED},
        "exact_match": round(sum(1 for r in rows if r["id"] not in {m["id"] for m in misses}) / n, 4),
        "by_tag": {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_tag.items())},
        "latency_ms_p50": round(latencies[n // 2] * 1000, 2),
        "latency_ms_p95": round(latencies[min(n - 1, int(n * 0.95))] * 1000, 2),
        "misses": misses,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    parser.add_argument("--extractor", default="rules", choices=["rules", "anthropic", "openai", "gemini"])
    parser.add_argument("--model", help="model name for anthropic/openai/gemini (overrides INTAKEGUARD_LLM_MODEL)")
    parser.add_argument("--dataset", default="core", help="core, hard, or a path to a .jsonl file")
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--report", type=Path, help="write the full JSON report here")
    args = parser.parse_args(argv)

    report = run(load(args.dataset), args.extractor, args.model)
    model = f" ({report['model']})" if report["model"] else ""
    print(f"extractor: {report['extractor']}{model}   dataset: {args.dataset}   documents: {report['documents']}")
    for field, acc in report["accuracy"].items():
        flag = "" if acc >= args.threshold else "   <-- below threshold"
        print(f"  {field:<14} {acc:6.2%}{flag}")
    print(f"  {'exact_match':<14} {report['exact_match']:6.2%}")
    if report["usage"]["calls"]:
        u = report["usage"]
        print(f"  tokens: {u['input_tokens']} in / {u['output_tokens']} out over {u['calls']} calls")
    print(f"  latency p50 {report['latency_ms_p50']} ms, p95 {report['latency_ms_p95']} ms")
    print("by tag: " + ", ".join(f"{t} {v}" for t, v in report["by_tag"].items()))
    for miss in report["misses"]:
        print(f"  MISS {miss['id']} {miss['field']}: expected {miss['expected']!r}, got {miss['got']!r}")
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [f for f, a in report["accuracy"].items() if a < args.threshold]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
