# Instructions for coding agents (Codex and others; same rules as CLAUDE.md)

This repo is set up so several agents can work in parallel without stepping on each other. Your role is in
`AGENT_ROLE` (`service`, `extraction`, `evals`, `tests`, `integrator`, `reviewer`). The `.claude/hooks/guard.py`
hook enforces the rules below on every tool call and fails closed if `AGENT_ROLE` is unset.

## Read first
1. `docs/ARCHITECTURE.md`: the contract (schema, statuses, interfaces, HTTP behaviour, guardrail rules)
2. `.claude/roles.json`: what your role may write and must not read

## Hard rules
- Write only the paths your role owns. If the guard blocks you, stop and report what you needed. Do not try
  another route around it.
- Never edit `docs/`, `intakeguard/sql/`, `.claude/`, `.github/`, `scripts/`, `CLAUDE.md`, `AGENTS.md`.
  If the contract looks wrong, say so in your final message and keep to it.
- Stay inside this worktree: no other worktrees or branches, no network except localhost, no package installs.
- Every SQL statement on tenant data filters by `tenant`.
- The extractor receives document text only. Never pass tenant names, claimant lists or secrets to it.
- Never log document text, secrets or API keys.
- Never weaken, skip or delete a test to make it pass. If a test is wrong, explain why and wait.
- Separation: the `extraction` role never sees `evals/`; the `evals` role never sees the extractors; the `tests`
  role writes tests from the contract without reading the implementation.

## Definition of done
`ruff check .`, `python -m pytest -q`, `python -m evals` and `python scripts/mutation_check.py` all pass.
Paste their output in your final message.

## Without the Claude Code hook
Tools that do not run `.claude/hooks/guard.py` must run in a sandbox limited to this worktree with no network.
CI re-checks everything on every push.
