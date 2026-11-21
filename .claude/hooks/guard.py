#!/usr/bin/env python3
"""PreToolUse guard: enforces per-role write scope, read separation, repo confinement.

Exit 2 = block (stderr is shown to the agent). Every decision is logged to .agent-logs/<role>.log,
which is our evidence of what each agent read and what was refused.
Fails closed: unknown/missing AGENT_ROLE blocks every tool call.
"""
import datetime
import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
ROLE = os.environ.get("AGENT_ROLE", "")
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GIT_SAFE = {"status", "add", "commit", "diff", "log", "ls-files", "rev-parse", "restore", "stash", "show-ref"}
OUTSIDE_OK = ("/tmp", "/dev/null", "/usr", "/bin")


def log(decision, tool, target):
    try:
        d = ROOT / ".agent-logs"
        d.mkdir(exist_ok=True)
        with open(d / f"{ROLE or 'NO_ROLE'}.log", "a") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {decision} {tool} {target}\n")
    except OSError:
        pass


def deny(tool, target, why):
    log("DENY", tool, f"{target} :: {why}")
    print(f"BLOCKED by guard ({ROLE or 'no role'}): {why}. Do not work around this; "
          f"report what you needed in your final message.", file=sys.stderr)
    sys.exit(2)


def rel(p):
    """Repo-relative posix path, or None if outside the repo."""
    path = Path(p)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return None


def hit(r, globs):
    return any(fnmatch.fnmatch(r, g) or r == g.rstrip("/*") for g in globs)


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}

    try:
        roles = json.loads((ROOT / ".claude" / "roles.json").read_text())
    except Exception as e:  # noqa: BLE001
        deny(tool, "-", f"cannot load roles.json ({e})")
    if ROLE not in roles or ROLE.startswith("_"):
        deny(tool, "-", "AGENT_ROLE missing or unknown; start the session as `AGENT_ROLE=<role> claude`")
    cfg = roles[ROLE]
    protected = roles["_protected"]

    if tool in {"WebFetch", "WebSearch"}:
        deny(tool, "-", "no network access for agents")

    if tool in WRITE_TOOLS:
        target = inp.get("file_path") or inp.get("notebook_path") or ""
        r = rel(target)
        if r is None:
            deny(tool, target, "path is outside this repository")
        if hit(r, protected):
            deny(tool, r, "contract/instruction/guard files are lead-only")
        if not hit(r, cfg["write"]):
            deny(tool, r, f"role '{ROLE}' may only write {cfg['write']}")
        log("ALLOW", tool, r)
        return

    if tool in READ_TOOLS:
        target = inp.get("file_path") or inp.get("path") or "."
        r = rel(target)
        if r is None:
            deny(tool, target, "path is outside this repository")
        pattern = " ".join(str(inp.get(k, "")) for k in ("pattern", "glob"))
        if hit(r, cfg["no_read"]) or any(t in pattern or t in r for t in cfg["forbid_tokens"]):
            deny(tool, r, "this path is separated from your role")
        # Searching a parent of a forbidden dir: allowed only if that dir is absent in this worktree.
        if tool in {"Grep", "Glob"}:
            for g in cfg["no_read"]:
                d = g.rstrip("/*")
                if (r in (".", "") or d.startswith(r + "/")) and (ROOT / d).exists():
                    deny(tool, r, f"search would cover separated path '{d}'; narrow the path")
        log("ALLOW", tool, r)
        return

    if tool == "Bash":
        cmd = inp.get("command", "")
        for t in cfg["forbid_tokens"]:
            if t in cmd:
                deny(tool, cmd, f"command mentions separated token '{t}'")
        if re.search(r"\.\./|(^|[\s=\"'])~", cmd):
            deny(tool, cmd, "no parent-dir or home-dir paths")
        if re.search(r"\b(curl|wget|nc|ssh|scp)\b", cmd) and not re.search(r"\b(127\.0\.0\.1|localhost)\b", cmd):
            deny(tool, cmd, "network only to localhost")
        if re.search(r"\b(pip|pip3|uv|poetry)\s+(install|add)\b", cmd):
            deny(tool, cmd, "no dependency installs; deps are fixed in requirements.txt")
        if re.search(r"\bsudo\b|\brm\s+-[a-z]*r[a-z]*f?\s+(/|\.)\s*$", cmd):
            deny(tool, cmd, "destructive command")
        for m in re.finditer(r"(?:^|[\s=\"'(<>])(/[^\s\"';|&)]+)", cmd):
            p = m.group(1)
            if rel(p) is None and not p.startswith(OUTSIDE_OK):
                deny(tool, cmd, f"absolute path outside repo: {p}")
        for m in re.finditer(r"(?:^|[\s=\"'(<>])([A-Za-z]:[\\/][^\s\"';|&)]*)", cmd):
            if rel(m.group(1)) is None:
                deny(tool, cmd, f"drive path outside repo: {m.group(1)}")
        if re.search(r"\$\{?(HOME|USERPROFILE|APPDATA|LOCALAPPDATA)\b|%(USERPROFILE|APPDATA)%|\$env:|USERPROFILE",
                     cmd, re.IGNORECASE):
            deny(tool, cmd, "no home-directory references")
        if not cfg.get("git_full"):
            try:
                words = shlex.split(cmd)
            except ValueError:
                words = cmd.split()
            for i, w in enumerate(words):
                if w == "git" and i + 1 < len(words):
                    sub = words[i + 1]
                    if sub not in GIT_SAFE:
                        deny(tool, cmd, f"'git {sub}' is lead/integrator-only (no other branches/worktrees, no push)")
        # Shell writes into protected files
        for g in protected:
            base = g.rstrip("/*")
            if re.search(rf"(>>?\s*|tee\s+(-a\s+)?|sed\s+-i[^|;]*\s|mv\s+[^|;]*\s|cp\s+[^|;]*\s|rm\s+[^|;]*|chmod\s+[^|;]*\s|truncate\s+[^|;]*\s)(\./)?{re.escape(base)}", cmd):
                deny(tool, cmd, f"shell write to protected path '{base}'")
        log("ALLOW", tool, cmd.replace("\n", " ")[:300])
        return

    log("ALLOW", tool, "-")


if __name__ == "__main__":
    main()
