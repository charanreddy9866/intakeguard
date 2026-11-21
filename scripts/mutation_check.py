"""Mutation check: remove each safety protection in a throwaway copy and confirm a test fails.

Run: python scripts/mutation_check.py   (exits 1 if any mutant survives)
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (what is removed, file, original text, replacement, test file, -k selector)
MUTANTS = [
    ("signature check bypassed",
     "intakeguard/api.py", "if reason:\n", "if False:\n",
     "test_webhook.py", "bad_signature"),
    ("ON CONFLICT removed",
     "intakeguard/api.py", '"ON CONFLICT(tenant, document_id) DO NOTHING",', '"",',
     "test_webhook.py", "duplicate"),
    ("claim condition removed",
     "intakeguard/worker.py",
     "AND (status = 'received' OR (status = 'processing' AND lease_expires_at < :now))\"", '"',
     "test_worker.py", "two_workers"),
    ("tenant filter removed from worker text lookup",
     "intakeguard/worker.py",
     '"SELECT text, attempts FROM documents WHERE tenant = ? AND document_id = ?",\n'
     "                               (tenant, document_id)",
     '"SELECT text, attempts FROM documents WHERE document_id = ? ORDER BY received_at",\n'
     "                               (document_id,)",
     "test_worker.py", "own_text"),
    ("lease fencing removed",
     "intakeguard/worker.py", "AND status = 'processing' AND lease_owner = :wid", "AND status = 'processing'",
     "test_worker.py", "lost_its_lease"),
    ("cross-tenant key check removed",
     "intakeguard/api.py", 'if row["tenant"] != tenant:', "if False:",
     "test_security_and_auth.py", "another_tenant"),
    ("calendar-date check removed",
     "intakeguard/guardrails.py", "dt.date.fromisoformat(date)", "pass",
     "test_worker.py", "bad_extractor"),
    ("case-file idempotency removed",
     "intakeguard/api.py", "INSERT OR IGNORE INTO case_file_entries", "INSERT INTO case_file_entries",
     "test_review_api.py", "twice"),
]


def run_mutant(file: str, old: str, new: str, test: str, selector: str) -> tuple[bool, str]:
    work = pathlib.Path(tempfile.mkdtemp())
    try:
        shutil.copytree(ROOT, work / "p", ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db*"))
        target = work / "p" / file
        source = target.read_text()
        if old not in source:
            raise SystemExit(f"mutation pattern not found in {file}: {old[:60]!r}")
        target.write_text(source.replace(old, new, 1))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"tests/{test}", "-k", selector],
            cwd=work / "p", capture_output=True, text=True, check=False,
        )
        summary = [line for line in result.stdout.splitlines() if " passed" in line or " failed" in line]
        return result.returncode != 0, (summary[-1] if summary else result.stdout[-200:])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    survived = 0
    for name, *args in MUTANTS:
        caught, summary = run_mutant(*args)
        survived += not caught
        print(f"{'CAUGHT' if caught else 'MISSED'}  {name:<45} {summary}")
    print(f"\n{len(MUTANTS) - survived}/{len(MUTANTS)} protections are guarded by a failing test")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
