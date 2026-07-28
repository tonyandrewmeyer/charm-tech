#!/usr/bin/env python3
"""Check: AGENTS.md content is trustworthy (Layer 1 staleness checks).
Tier coverage: product, canonical, personal.

Implements the five Layer 1 checks from
roadmap/26.10/repo-setup/agents-md-validation.md (canonical-work-queue):

1. Commands parse and their entry-point tool resolves in a dev environment.
2. Safe commands actually pass: runnable (lint/format-check/unit-test/build)
   commands are executed and must exit 0; environment-gated commands
   (integration needing Docker/LXD/juju, root-only tests, anything that would
   mutate the tree or start a long-running process) are only parsed and
   reported verify-manually, with the gating dependency named.
3. Paths and symbols resolve: every referenced file exists; every named
   gocheck test suite (`-check.f <Suite>` after a `go test <package>`) still
   lives in the named package; every "`Symbol` in `path`" reference resolves.
4. Version pins mentioned in prose (`tool@vX.Y.Z`) match what
   .github/workflows actually pin.
5. Scope lint: flag harness-shaped content (attribution trailers, tool
   hints, per-agent config) that belongs in harness config, not AGENTS.md.

This is a content check, not a presence check — see agents-md.py for
presence/length. If AGENTS.md is absent this check is n/a.

Convention: one script emits exactly one JSON result (see lib/common.py);
all five sub-checks are folded into a single pass/fail with per-sub-check
evidence, following check.py's one-line-of-JSON-per-script contract.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.common import (
    EXIT_FAIL, EXIT_NA, EXIT_PASS,
    cd_repo_root, emit_check, parse_tier, run, tier_applies,
)

CHECK_ID = "agents-md-content"
APPLIES = "product,canonical,personal"

RUNNABLE_TIMEOUT_SECONDS = 180

FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)\n(.*?)\n?```", re.DOTALL)
FENCE_LANGS = {"", "bash", "sh", "shell", "console", "zsh"}
TABLE_ROW_RE = re.compile(r"^\|(.+)\|[ \t]*$")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
COMMAND_ENTRYPOINTS = {
    "go", "tox", "make", "uv", "pytest", "docker", "npm", "cargo", "python",
    "python3", "pip", "sudo", "gofmt", "staticcheck", "govulncheck", "ruff",
    "black", "flake8", "pyright", "ty", "mypy", "just",
}
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Check 2 classification. Order matters: side-effecting first, then
# environment-gate keywords, then the runnable allowlist. Anything matching
# none of these is treated conservatively as environment-gated ("not
# recognised as safe" rather than risk running an unknown command).
SIDE_EFFECT_RE = re.compile(
    r"\bgo run\b|\bgo install\b|\bgo fmt\b(?!.*-l)|\bpip install\b"
    r"|\buv tool install\b|\buv pip install\b|(?:tox -e|make)\s+format\b"
    r"|\bruff format\b(?!.*(--check|--diff))|\bblack\b(?!.*--check)"
    r"|\bmake\s+run\b|\bmake\s+cli-help\b|\bnpm install\b"
)
ENV_GATE_PATTERNS = [
    (re.compile(r"\bdocker\b|\bcompose\b", re.IGNORECASE), "Docker"),
    (re.compile(r"\blxd\b", re.IGNORECASE), "LXD"),
    (re.compile(r"\bjuju\b", re.IGNORECASE), "juju"),
    (re.compile(r"\bcharmcraft\b", re.IGNORECASE), "charmcraft"),
    (re.compile(r"\bsudo\b|\broot\b", re.IGNORECASE), "root/sudo"),
    (re.compile(r"\bintegration\b", re.IGNORECASE), "integration environment"),
    (re.compile(r"CHARM_PATH|packed charms?", re.IGNORECASE), "packed charms"),
]
RUNNABLE_HINT_RE = re.compile(
    r"\btest\b|\bunit\b|\bpytest\b|\blint\b|\bbuild\b|\bvet\b|--check\b|--diff\b"
    r"|staticcheck|govulncheck|pyright|\bty check\b|gofmt -l",
    re.IGNORECASE,
)

VERSION_PIN_RE = re.compile(r"([A-Za-z0-9_.\-/]+)@v(\d+\.\d+(?:\.\d+)?)")
SUITE_RE = re.compile(
    r"go test\s+(\.[^\s]+)\s+.*-check\.f[= ]([A-Za-z_][A-Za-z0-9_]*)"
)
SYMBOL_IN_PATH_RE = re.compile(r"`([A-Za-z_][\w.]*)`\s+in\s+`([^`]+)`")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FILE_EXT_RE = re.compile(
    r"\.(md|py|go|toml|yaml|yml|txt|cfg|ini|sh|json|lock)$", re.IGNORECASE
)
KNOWN_EXTENSIONLESS_FILENAMES = {"dockerfile", "makefile", "license", "copying"}

SCOPE_LINT_PATTERNS = [
    (re.compile(r"Co-Authored-By", re.IGNORECASE), "attribution trailer (Co-Authored-By)"),
    (re.compile(r"Generated (with|by)\s*\[?Claude", re.IGNORECASE), "Claude attribution line"),
    (re.compile(r"Claude Code", re.IGNORECASE), "harness name (Claude Code)"),
    (re.compile(r"claude\.ai/code", re.IGNORECASE), "harness URL (claude.ai/code)"),
    (re.compile(r"GitHub Copilot|\bCopilot\b"), "harness name (Copilot)"),
    (re.compile(r"\bChatGPT\b|\bOpenAI\b"), "harness name (ChatGPT/OpenAI)"),
    (re.compile(r"\bAnthropic\b"), "harness vendor name (Anthropic)"),
    (re.compile(r"\U0001F916"), "robot-emoji attribution marker"),
    (re.compile(r"\.claude/"), "harness-specific config path (.claude/)"),
]


def extract_commands(text: str) -> list[tuple[str, str]]:
    """Return (raw_command, source) pairs from fenced shell blocks and
    markdown table cells that look like commands."""
    commands: list[tuple[str, str]] = []
    for m in FENCE_RE.finditer(text):
        lang = m.group(1).lower()
        if lang not in FENCE_LANGS:
            continue
        for line in m.group(2).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cmd = re.split(r"\s+#\s?", line, maxsplit=1)[0].strip()
            if cmd:
                commands.append((cmd, "fenced"))
    for line in text.splitlines():
        row = TABLE_ROW_RE.match(line.strip())
        if not row:
            continue
        for cell in row.group(1).split("|"):
            cell = cell.strip()
            code_m = INLINE_CODE_RE.fullmatch(cell)
            if not code_m:
                continue
            candidate = code_m.group(1).strip()
            first_tok = candidate.split()[0] if candidate.split() else ""
            if first_tok in COMMAND_ENTRYPOINTS:
                commands.append((candidate, "table"))
    return commands


def entry_point_tool(cmd: str) -> str:
    """First non-assignment token of the whole command line. A tool
    introduced mid-line by an explicit install step (e.g. `go install X &&
    X ...`) is intentionally not checked here — it's expected to be absent
    until that install step runs."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return ""
    for tok in tokens:
        if ENV_ASSIGN_RE.match(tok):
            continue
        return tok
    return ""


def classify_command(cmd: str) -> tuple[str, str]:
    """Return (bucket, reason). bucket is 'runnable' or 'environment-gated'."""
    if SIDE_EFFECT_RE.search(cmd):
        return (
            "environment-gated",
            "would mutate the working tree or start a long-running process — not executed automatically",
        )
    for pattern, name in ENV_GATE_PATTERNS:
        if pattern.search(cmd):
            return "environment-gated", name
    if RUNNABLE_HINT_RE.search(cmd):
        return "runnable", ""
    return "environment-gated", "not recognised as a safe check command — verify manually"


def looks_like_path(cand: str) -> bool:
    if not cand or " " in cand or cand.startswith(("http://", "https://")):
        return False
    if "/" in cand:
        # Exclude Go/domain-style import paths (github.com/..., gopkg.in/...,
        # golang.org/..., honnef.co/...) — a dotted first segment that isn't
        # itself a relative-path marker ("." / "..") means "module path",
        # not "local file".
        first_seg = cand.split("/", 1)[0]
        if "." in first_seg and not first_seg.startswith("."):
            return False
        return True
    if cand.startswith("."):
        return True
    if FILE_EXT_RE.search(cand):
        return True
    return cand.lower() in KNOWN_EXTENSIONLESS_FILENAMES


def extract_referenced_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for m in MD_LINK_RE.finditer(text):
        target = m.group(1)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        paths.add(target)
    for m in INLINE_CODE_RE.finditer(text):
        cand = m.group(1).strip()
        if looks_like_path(cand):
            paths.add(cand)
    return paths


def workflow_texts(root: Path) -> dict[str, str]:
    wf_dir = root / ".github" / "workflows"
    out: dict[str, str] = {}
    if not wf_dir.is_dir():
        return out
    for p in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        try:
            out[str(p.relative_to(root))] = p.read_text(errors="replace")
        except OSError:
            continue
    return out


def check_version_drift(
    pins: list[tuple[str, str]], workflows: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """Return (drifted, checked). checked includes every pin that could be
    cross-referenced against a workflow (pass or fail), for evidence
    transparency — e.g. a tool version pinned differently in an unrelated
    workflow is visible even when the AGENTS.md claim matches somewhere."""
    drifted: list[dict] = []
    checked: list[dict] = []
    for tool, doc_version in pins:
        found: set[str] = set()
        for text in workflows.values():
            for vm in re.finditer(re.escape(tool) + r"@v(\d+\.\d+(?:\.\d+)?)", text):
                found.add(f"v{vm.group(1)}")
        if not found:
            continue
        entry = {"tool": tool, "doc_version": doc_version, "ci_versions": sorted(found)}
        checked.append(entry)
        if doc_version not in found:
            drifted.append(entry)
    return drifted, checked


def scope_lint(text: str) -> list[str]:
    return [label for pattern, label in SCOPE_LINT_PATTERNS if pattern.search(text)]


def main() -> int:
    tier = parse_tier()
    if not tier_applies(APPLIES, tier):
        emit_check(CHECK_ID, "na", f"Not applicable for tier {tier}.")
        return EXIT_NA

    root = cd_repo_root()

    p = Path("AGENTS.md")
    if not p.is_file():
        emit_check(
            CHECK_ID, "na",
            "No AGENTS.md to content-check (see agents-md check for presence).",
        )
        return EXIT_NA

    text = p.read_text(errors="replace")

    # --- Checks 1 & 2: commands ---
    commands = extract_commands(text)
    missing_tools: list[dict] = []
    seen_missing_tools: set[str] = set()
    runnable_results: list[dict] = []
    gated: list[dict] = []

    for cmd, source in commands:
        tool = entry_point_tool(cmd)
        if tool and tool not in seen_missing_tools and shutil.which(tool) is None:
            seen_missing_tools.add(tool)
            missing_tools.append({"command": cmd, "tool": tool})

        bucket, reason = classify_command(cmd)
        if bucket == "environment-gated":
            gated.append({"command": cmd, "gating_dependency": reason})
            continue

        try:
            tokens = shlex.split(cmd)
        except ValueError:
            runnable_results.append({"command": cmd, "status": "unparseable"})
            continue
        try:
            proc = run(tokens, cwd=root, timeout=RUNNABLE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            runnable_results.append({"command": cmd, "status": "timeout"})
            continue
        except OSError as exc:
            runnable_results.append({"command": cmd, "status": "error", "detail": str(exc)})
            continue
        runnable_results.append({
            "command": cmd,
            "status": "pass" if proc.returncode == 0 else "fail",
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-500:] if proc.returncode != 0 else "",
        })

    failed_runnable = [r for r in runnable_results if r["status"] != "pass"]

    # --- Check 3: paths & symbols ---
    ref_paths = extract_referenced_paths(text)
    missing_paths = sorted(rp for rp in ref_paths if not (root / rp).exists())

    symbol_findings: list[dict] = []
    for sym, sym_path in SYMBOL_IN_PATH_RE.findall(text):
        target = root / sym_path
        if not target.is_file():
            symbol_findings.append({"symbol": sym, "path": sym_path, "problem": "path does not exist"})
            continue
        body = target.read_text(errors="replace")
        if not re.search(rf"\b{re.escape(sym)}\b", body):
            symbol_findings.append({"symbol": sym, "path": sym_path, "problem": "symbol not found in file"})

    suite_findings: list[dict] = []
    for pkg, suite in SUITE_RE.findall(text):
        pkg_dir = (root / pkg).resolve()
        if not pkg_dir.is_dir():
            suite_findings.append({"suite": suite, "package": pkg, "problem": "package directory does not exist"})
            continue
        found = False
        for go_file in pkg_dir.rglob("*.go"):
            try:
                if re.search(rf"\b{re.escape(suite)}\b", go_file.read_text(errors="replace")):
                    found = True
                    break
            except OSError:
                continue
        if not found:
            suite_findings.append({"suite": suite, "package": pkg, "problem": "suite identifier not found anywhere in package"})

    # --- Check 4: version pins vs CI ---
    pins = [
        (path.rstrip("/").split("/")[-1], f"v{ver}")
        for path, ver in VERSION_PIN_RE.findall(text)
    ]
    workflows = workflow_texts(root)
    version_drift, version_checked = check_version_drift(pins, workflows)

    # --- Check 5: scope lint ---
    scope_findings = scope_lint(text)

    problems: list[str] = []
    if missing_tools:
        problems.append(f"{len(missing_tools)} command tool(s) not resolvable")
    if failed_runnable:
        problems.append(f"{len(failed_runnable)} runnable command(s) did not pass")
    if missing_paths:
        problems.append(f"{len(missing_paths)} referenced path(s) missing")
    if symbol_findings:
        problems.append(f"{len(symbol_findings)} referenced symbol(s) unresolved")
    if suite_findings:
        problems.append(f"{len(suite_findings)} named test suite(s) not found in package")
    if version_drift:
        problems.append(f"{len(version_drift)} version pin(s) drifted from CI")
    if scope_findings:
        problems.append(f"{len(scope_findings)} scope-lint finding(s) (harness-shaped content)")

    evidence = {
        "path": "AGENTS.md",
        "commands_extracted": len(commands),
        "missing_tools": missing_tools,
        "runnable_checked": len(runnable_results),
        "runnable_failed": failed_runnable,
        "environment_gated": gated,
        "paths_checked": sorted(ref_paths),
        "missing_paths": missing_paths,
        "symbol_findings": symbol_findings,
        "suite_findings": suite_findings,
        "version_pins_checked": version_checked,
        "version_drift": version_drift,
        "scope_lint_findings": scope_findings,
    }

    if problems:
        emit_check(
            CHECK_ID, "fail",
            "AGENTS.md content check: " + "; ".join(problems) + ".",
            evidence,
            {
                "kind": "judgement",
                "human_review": (
                    "Review the evidence fields for the failing sub-check(s) "
                    "(missing_tools / runnable_failed / missing_paths / "
                    "symbol_findings / suite_findings / version_drift / "
                    "scope_lint_findings) and update AGENTS.md or the "
                    "underlying repo to match."
                ),
            },
        )
        return EXIT_FAIL

    emit_check(
        CHECK_ID, "pass",
        f"AGENTS.md content verified: {len(commands)} command(s) parsed "
        f"({len(runnable_results)} run, {len(gated)} environment-gated/"
        f"verify-manually), {len(ref_paths)} path(s) resolved, "
        f"{len(version_checked)} version pin(s) cross-checked against CI, "
        "no scope-lint findings.",
        evidence,
    )
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
