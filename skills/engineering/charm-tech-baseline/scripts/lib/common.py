"""Shared helpers for charm-tech-baseline skill checks and fixes.

Imported by every check / fix script. No side effects on import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


# Exit codes. Every check script exits with one of these.
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NA = 2
EXIT_UNKNOWN = 3


def repo_root() -> Path:
    """Return the repo root. Falls back to CWD when not inside a git tree
    (the skill can be invoked against an unpacked tarball, for example)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path.cwd()


def origin_url() -> str:
    """Return the origin remote URL normalised to https form, without a
    trailing .git. Empty string if no origin remote."""
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:"):]
    if url.endswith(".git"):
        url = url[:-4]
    return url


def emit_check(
    check_id: str,
    status: str,
    summary: str,
    evidence: dict[str, Any] | None = None,
    remediation: dict[str, Any] | None = None,
) -> None:
    """Emit a single check result as a JSON object on one line to stdout.

    status is one of: pass, fail, na, unknown.
    """
    payload = {
        "id": check_id,
        "status": status,
        "summary": summary,
        "evidence": evidence if evidence is not None else {},
        "remediation": remediation,
    }
    # Single-line JSON so the umbrella runner can concatenate outputs.
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    sys.stdout.write("\n")


def tier_applies(check_tiers: str | Iterable[str], current_tier: str) -> bool:
    """True when the current tier is in the check's applicable tiers.

    check_tiers may be a comma-separated string ("product,canonical") or
    any iterable of strings.
    """
    if isinstance(check_tiers, str):
        tiers = {t.strip() for t in check_tiers.split(",") if t.strip()}
    else:
        tiers = set(check_tiers)
    return current_tier in tiers


def parse_tier(argv: list[str] | None = None) -> str:
    """Extract --tier=<value> from argv. Returns empty string if absent.

    Unknown flags are ignored (each check only cares about --tier)."""
    args = argv if argv is not None else sys.argv[1:]
    for arg in args:
        if arg.startswith("--tier="):
            return arg[len("--tier="):]
    return ""


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Convenience wrapper around subprocess.run with text=True and
    capture_output=True by default. Never raises on non-zero exit —
    callers should inspect .returncode."""
    kwargs.setdefault("text", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)


def cd_repo_root() -> Path:
    """Chdir to the repo root and return it. Exits EXIT_UNKNOWN if the
    root cannot be reached (matches the shell behaviour of `cd || exit 3`)."""
    root = repo_root()
    try:
        os.chdir(root)
    except OSError:
        sys.exit(EXIT_UNKNOWN)
    return root
