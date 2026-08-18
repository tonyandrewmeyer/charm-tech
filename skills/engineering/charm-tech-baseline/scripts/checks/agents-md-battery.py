#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Check: this repo's AGENTS.md question battery still describes the repo.
Tier coverage: product, canonical, personal.

A question battery (assets/question-batteries/<repo>.yaml) records, for each
AGENTS.md line that earns its place, the question an agent would be asked, the
checkable answer, the source line it derives from, and the override/cache
classification. It makes Layer 2 behavioural re-tests mechanical to run when
Layer 1 or Layer 3 triggers them. Schema and rationale:
references/question-batteries.md.

This check validates the battery against the repo:

1. Schema — every entry has the required fields with known enum values.
2. Source lines — every `source_line` still appears in AGENTS.md (whitespace
   collapsed on both sides, so a line that wraps in the file still matches).
3. Assertions — every `verify` assertion still holds: paths resolve, patterns
   match, named gocheck suites still live in the named package.

Assertions are static by design. Layer 1's agents-md-content check already
classifies and executes the commands; running them here too would double the
runtime and the environment surface for no new signal.

Batteries exist only for repos that have been through the Layer 2 authoring
gate. A repo with no battery is `na`, not a gap.

Convention: one script emits exactly one JSON result (see lib/common.py).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.common import (
    EXIT_FAIL, EXIT_NA, EXIT_PASS,
    cd_repo_root, emit_check, origin_url, parse_tier, tier_applies,
)

import yaml

CHECK_ID = "agents-md-battery"
APPLIES = "product,canonical,personal"

BATTERIES_DIR = Path(__file__).parent.parent.parent / "assets" / "question-batteries"

CLASSIFICATIONS = {"override", "cache"}
GRADES = {"command", "keywords", "judgement"}
VERIFY_KINDS = {"path_exists", "text_in_file", "suite_in_package", "none"}
REQUIRED_ENTRY_KEYS = {
    "id", "question", "classification", "source_line", "answer",
    "verify", "ci_verifiable",
}


def parse_flag(name: str) -> str:
    prefix = f"--{name}="
    for arg in sys.argv[1:]:
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return ""


def battery_path() -> Path | None:
    """Explicit --battery=<path> wins; otherwise the battery named after the
    repo the origin URL points at."""
    explicit = parse_flag("battery")
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    url = origin_url()
    if not url:
        return None
    name = url.rstrip("/").split("/")[-1]
    candidate = BATTERIES_DIR / f"{name}.yaml"
    return candidate if candidate.is_file() else None


def collapse(text: str) -> str:
    return " ".join(text.split())


def validate_schema(entry: dict, index: int) -> list[str]:
    where = entry.get("id") or f"entry[{index}]"
    problems = []
    for key in sorted(REQUIRED_ENTRY_KEYS - set(entry)):
        problems.append(f"{where}: missing required key '{key}'")
    if entry.get("classification") not in CLASSIFICATIONS and "classification" in entry:
        problems.append(f"{where}: unknown classification {entry['classification']!r}")

    answer = entry.get("answer")
    if isinstance(answer, dict):
        grade = answer.get("grade")
        if grade not in GRADES:
            problems.append(f"{where}: unknown answer.grade {grade!r}")
        elif grade == "command" and not answer.get("expect"):
            problems.append(f"{where}: answer.grade 'command' needs 'expect'")
        elif grade == "keywords" and not answer.get("require"):
            problems.append(f"{where}: answer.grade 'keywords' needs 'require'")
        elif grade == "judgement" and not answer.get("rubric"):
            problems.append(f"{where}: answer.grade 'judgement' needs 'rubric'")
    elif "answer" in entry:
        problems.append(f"{where}: 'answer' must be a mapping")

    verify = entry.get("verify")
    if isinstance(verify, list) and verify:
        for assertion in verify:
            if not isinstance(assertion, dict):
                problems.append(f"{where}: each verify assertion must be a mapping")
                continue
            kind = assertion.get("kind")
            if kind not in VERIFY_KINDS:
                problems.append(f"{where}: unknown verify kind {kind!r}")
            elif kind == "none" and not assertion.get("reason"):
                problems.append(f"{where}: verify kind 'none' needs 'reason'")
    elif "verify" in entry:
        problems.append(f"{where}: 'verify' must be a non-empty list")

    if entry.get("ci_verifiable") is False and not entry.get("gated_by"):
        problems.append(f"{where}: ci_verifiable false needs 'gated_by'")
    return problems


def run_assertion(assertion: dict, entry_id: str, root: Path) -> dict | None:
    """Return a finding dict when the assertion fails, else None."""
    kind = assertion["kind"]
    if kind == "none":
        return None

    if kind == "path_exists":
        rel = assertion.get("path", "")
        if not (root / rel).exists():
            return {"entry": entry_id, "kind": kind, "path": rel,
                    "problem": "path does not exist"}
        return None

    if kind == "text_in_file":
        rel = assertion.get("file", "")
        pattern = assertion.get("pattern", "")
        target = root / rel
        if not target.is_file():
            return {"entry": entry_id, "kind": kind, "file": rel,
                    "problem": "file does not exist"}
        try:
            compiled = re.compile(pattern, re.MULTILINE)
        except re.error as exc:
            return {"entry": entry_id, "kind": kind, "file": rel,
                    "pattern": pattern, "problem": f"invalid pattern: {exc}"}
        if not compiled.search(target.read_text(errors="replace")):
            return {"entry": entry_id, "kind": kind, "file": rel,
                    "pattern": pattern, "problem": "pattern not found in file"}
        return None

    # suite_in_package
    suite = assertion.get("suite", "")
    package = assertion.get("package", "")
    pkg_dir = root / package
    if not pkg_dir.is_dir():
        return {"entry": entry_id, "kind": kind, "suite": suite, "package": package,
                "problem": "package directory does not exist"}
    needle = re.compile(rf"\b{re.escape(suite)}\b")
    for go_file in pkg_dir.rglob("*.go"):
        try:
            if needle.search(go_file.read_text(errors="replace")):
                return None
        except OSError:
            continue
    return {"entry": entry_id, "kind": kind, "suite": suite, "package": package,
            "problem": "suite identifier not found anywhere in package"}


def main() -> int:
    tier = parse_tier()
    if not tier_applies(APPLIES, tier):
        emit_check(CHECK_ID, "na", f"Not applicable for tier {tier}.")
        return EXIT_NA

    root = cd_repo_root()

    path = battery_path()
    if path is None:
        emit_check(
            CHECK_ID, "na",
            "No question battery for this repo — it has not been through the "
            "Layer 2 authoring gate (see references/question-batteries.md).",
        )
        return EXIT_NA

    try:
        battery = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        emit_check(CHECK_ID, "fail", f"Battery {path.name} is not valid YAML: {exc}")
        return EXIT_FAIL

    entries = battery.get("entries") or []
    agents_md = root / "AGENTS.md"
    if not agents_md.is_file():
        emit_check(
            CHECK_ID, "fail",
            f"Battery {path.name} describes {len(entries)} AGENTS.md line(s), "
            "but the repo has no AGENTS.md.",
            {"battery": path.name, "entries_total": len(entries)},
            {"kind": "judgement",
             "human_review": "Restore AGENTS.md or retire the battery."},
        )
        return EXIT_FAIL

    md_text = agents_md.read_text(errors="replace")
    md_collapsed = collapse(md_text)

    schema_findings: list[str] = []
    drifted: list[dict] = []
    verify_findings: list[dict] = []
    by_class: dict[str, int] = {}
    by_grade: dict[str, int] = {}
    unanchored: list[str] = []
    not_ci_verifiable: list[dict] = []

    for i, entry in enumerate(entries):
        schema_findings.extend(validate_schema(entry, i))
        entry_id = entry.get("id") or f"entry[{i}]"

        by_class[entry.get("classification", "unknown")] = (
            by_class.get(entry.get("classification", "unknown"), 0) + 1
        )
        grade = (entry.get("answer") or {}).get("grade", "unknown")
        by_grade[grade] = by_grade.get(grade, 0) + 1

        source_line = entry.get("source_line", "")
        if source_line and collapse(source_line) not in md_collapsed:
            drifted.append({"entry": entry_id, "source_line": source_line})

        for assertion in entry.get("verify") or []:
            if not isinstance(assertion, dict) or assertion.get("kind") not in VERIFY_KINDS:
                continue
            if assertion["kind"] == "none":
                unanchored.append(entry_id)
                continue
            finding = run_assertion(assertion, entry_id, root)
            if finding:
                verify_findings.append(finding)

        if entry.get("ci_verifiable") is False:
            not_ci_verifiable.append(
                {"entry": entry_id, "gated_by": entry.get("gated_by", "")}
            )

    seeded_digest = (battery.get("source") or {}).get("agents_md_sha256", "")
    current_digest = hashlib.sha256(md_text.encode()).hexdigest()

    evidence = {
        "battery": path.name,
        "entries_total": len(entries),
        "entries_by_classification": by_class,
        "entries_by_answer_grade": by_grade,
        "drifted_source_lines": drifted,
        "verify_findings": verify_findings,
        "schema_findings": schema_findings,
        "unanchored_entries": unanchored,
        "not_ci_verifiable": not_ci_verifiable,
        # Non-failing re-test trigger, not a defect: the file may have improved.
        "agents_md_changed_since_seeding": bool(seeded_digest)
        and seeded_digest != current_digest,
    }

    problems = []
    if schema_findings:
        problems.append(f"{len(schema_findings)} schema finding(s)")
    if drifted:
        problems.append(f"{len(drifted)} source line(s) no longer in AGENTS.md")
    if verify_findings:
        problems.append(f"{len(verify_findings)} verify assertion(s) failed")

    if problems:
        emit_check(
            CHECK_ID, "fail",
            f"Question battery {path.name}: " + "; ".join(problems) + ".",
            evidence,
            {
                "kind": "judgement",
                "human_review": (
                    "A drifted source line or failed assertion means the repo "
                    "moved under the battery. Re-run the Layer 2 gate for the "
                    "affected entries, then update AGENTS.md and the battery "
                    "together."
                ),
            },
        )
        return EXIT_FAIL

    emit_check(
        CHECK_ID, "pass",
        f"Question battery {path.name} matches AGENTS.md: {len(entries)} "
        f"entr(ies) anchored, {len(unanchored)} with no repo anchor by design, "
        f"{len(not_ci_verifiable)} not confirmable by an automated run.",
        evidence,
    )
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
