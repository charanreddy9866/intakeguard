"""Tiny dependency-free Prometheus-style counters (process-local) plus DB gauges rendered on scrape."""
from __future__ import annotations

import sqlite3
import threading
from collections import Counter

_lock = threading.Lock()
_counters: Counter[tuple[str, tuple[tuple[str, str], ...]]] = Counter()


def inc(name: str, **labels: str) -> None:
    with _lock:
        _counters[(name, tuple(sorted(labels.items())))] += 1


def reset() -> None:
    with _lock:
        _counters.clear()


def render(conn: sqlite3.Connection) -> str:
    lines: list[str] = []
    with _lock:
        items = sorted(_counters.items())
    for (name, labels), value in items:
        label_text = ",".join(f'{k}="{v}"' for k, v in labels)
        lines.append(f"intakeguard_{name}{{{label_text}}} {value}")
    for row in conn.execute("SELECT tenant, status, COUNT(*) AS n FROM documents GROUP BY tenant, status"):
        lines.append(f'intakeguard_documents{{tenant="{row["tenant"]}",status="{row["status"]}"}} {row["n"]}')
    review = conn.execute("SELECT COUNT(*) FROM documents WHERE status='pending' AND needs_review=1").fetchone()[0]
    lines.append(f"intakeguard_review_queue_depth {review}")
    return "\n".join(lines) + "\n"
