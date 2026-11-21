"""Compare extractors on every eval dataset and write a Markdown results table.

    python -m evals.compare rules
    python -m evals.compare rules anthropic:claude-haiku-5-5@<in>/<out> openai:<model>@<in>/<out>

Each run is `kind[:model][@input_price/output_price]`, prices in USD per million tokens (optional; check your
provider's current price list). Results go to stdout and to evals/results.md (override with --out).
API keys come from ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY. Never commit them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.__main__ import DATASETS, GATED, load, run

OUT = Path(__file__).resolve().parent / "results.md"


@dataclass
class RunSpec:
    kind: str
    model: str | None = None
    price_in: float | None = None
    price_out: float | None = None

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.model}" if self.model else self.kind


def parse_spec(spec: str) -> RunSpec:
    head, _, prices = spec.partition("@")
    kind, _, model = head.partition(":")
    price_in = price_out = None
    if prices:
        a, _, b = prices.partition("/")
        price_in, price_out = float(a), float(b)
    if kind not in ("rules", "anthropic", "openai", "gemini"):
        raise ValueError(f"unknown extractor kind in {spec!r}")
    return RunSpec(kind, model or None, price_in, price_out)


def cost_per_1k_docs(report: dict, spec: RunSpec) -> str:
    if spec.kind == "rules":
        return "$0"
    if spec.price_in is None:
        return "n/a"
    u = report["usage"]
    usd = (u["input_tokens"] * spec.price_in + u["output_tokens"] * spec.price_out) / 1_000_000
    return f"${usd / report['documents'] * 1000:.2f}"


def table(results: list[tuple[RunSpec, str, dict]]) -> str:
    head = ["extractor", "dataset", *GATED, "exact", "errors", "p50 ms", "tokens/doc", "cost / 1k docs"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for spec, dataset, r in results:
        n = r["documents"]
        answered = n - r["extractor_errors"]
        total = r["usage"]["input_tokens"] + r["usage"]["output_tokens"]
        tokens = total / answered if answered and r["usage"]["calls"] else 0
        cells = [f"`{spec.label}`", dataset, *(f"{r['accuracy'][f]:.0%}" for f in GATED),
                 f"{r['exact_match']:.0%}", f"{r['extractor_errors']}/{n}", f"{r['latency_ms_p50']:.0f}",
                 f"{tokens:.0f}",
                 cost_per_1k_docs(r, spec)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.compare")
    parser.add_argument("runs", nargs="+", help="kind[:model][@in/out] e.g. anthropic:claude-haiku-5-5@1/5")
    parser.add_argument("--datasets", default=",".join(DATASETS), help="comma-separated: core,hard")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between documents, for rate limits")
    args = parser.parse_args(argv)

    specs = [parse_spec(s) for s in args.runs]
    results, misses = [], []
    for spec in specs:
        for dataset in args.datasets.split(","):
            print(f"running {spec.label} on {dataset} ...", file=sys.stderr)
            report = run(load(dataset), spec.kind, spec.model, delay=0.0 if spec.kind == "rules" else args.delay)
            results.append((spec, dataset, report))
            misses += [f"- `{spec.label}` {dataset} {m['id']} {m['field']}: expected `{m['expected']}`, "
                       f"got `{m['got']}` {m['reasons']}" for m in report["misses"]]
            if report["extractor_errors"]:
                print(f"  WARNING: {report['extractor_errors']}/{report['documents']} documents got no answer "
                      "(rate limit or API error); rerun with --delay", file=sys.stderr)

    md = (f"# Eval results\n\nGenerated {dt.date.today().isoformat()} with `python -m evals.compare "
          f"{' '.join(args.runs)}`.\n\n{table(results)}\n\n"
          "Fields are scored after guardrails, i.e. on what would actually be stored. `needs_review` checks that "
          "a document is sent to a human exactly when it should be. `errors` counts documents where the provider "
          "returned no usable answer (timeouts, rate limits); a row with errors does not measure model accuracy."
          "\n\n<details><summary>Misses</summary>\n\n"
          + ("\n".join(misses) or "none") + "\n\n</details>\n")
    args.out.write_text(md, encoding="utf-8")
    print(table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
