"""AGENTS.md question battery validation (Layer 2 seed data, checked statically)."""
from __future__ import annotations

import hashlib
import textwrap


AGENTS_MD = textwrap.dedent("""\
    # AGENTS.md

    ## Test

    ```bash
    go test ./internals/cli -check.f MySuite   # single gocheck suite
    ```

    See [HACKING.md](HACKING.md). CI also rejects any use of `interface{}` —
    write `any`.
    """)

BATTERY = textwrap.dedent("""\
    schema_version: 1
    repo: example
    upstream: canonical/example
    source:
      agents_md_ref: chore/agents-md
      agents_md_sha: deadbeef
      agents_md_sha256: {digest}
      seeded_from: design doc
      seeded_on: 2026-08-19
    entries:
      - id: single-suite
        question: How do you run just MySuite?
        classification: cache
        source_line: "go test ./internals/cli -check.f MySuite # single gocheck suite"
        answer:
          grade: command
          expect: go test ./internals/cli -check.f MySuite
        verify:
          - kind: suite_in_package
            suite: MySuite
            package: internals/cli
        ci_verifiable: true
      - id: no-empty-interface
        question: What do you write instead of `interface{{}}`?
        classification: override
        source_line: CI also rejects any use of `interface{{}}` — write `any`.
        answer:
          grade: keywords
          require:
            - any
        verify:
          - kind: path_exists
            path: HACKING.md
        ci_verifiable: true
    """)

TREE = {
    "AGENTS.md": AGENTS_MD,
    "HACKING.md": "# Hacking\n",
    "internals/cli/suite_test.go": "package cli\n\ntype MySuite struct{}\n",
}


def battery() -> str:
    return BATTERY.format(digest=hashlib.sha256(AGENTS_MD.encode()).hexdigest())


def run(run_check, files: dict[str, str], battery_text: str) -> dict:
    return run_check(
        "agents-md-battery", "canonical",
        {**files, "battery.yaml": battery_text},
        ("--battery=battery.yaml",),
    )


def test_na_when_no_battery_for_repo(run_check):
    # No --battery and no origin remote to name one: not a gap, just a repo
    # that hasn't been through the Layer 2 authoring gate.
    r = run_check("agents-md-battery", "canonical", TREE)
    assert r["status"] == "na"


def test_pass_when_battery_matches_repo(run_check):
    r = run(run_check, TREE, battery())
    assert r["status"] == "pass"
    assert r["evidence"]["drifted_source_lines"] == []
    assert r["evidence"]["verify_findings"] == []
    assert r["evidence"]["entries_by_classification"] == {"cache": 1, "override": 1}


def test_source_line_matches_across_a_wrapped_line(run_check):
    # The interface{} source line wraps in AGENTS.md; whitespace is collapsed
    # on both sides so a single-line entry still matches.
    r = run(run_check, TREE, battery())
    assert r["status"] == "pass"


def test_fail_when_source_line_no_longer_in_agents_md(run_check):
    b = battery().replace("write `any`.", "write `anything`.")
    r = run(run_check, TREE, b)
    assert r["status"] == "fail"
    assert [d["entry"] for d in r["evidence"]["drifted_source_lines"]] == [
        "no-empty-interface"
    ]


def test_fail_when_suite_no_longer_in_named_package(run_check):
    # The canonical Layer 1 case, carried into the battery: pebble's
    # PebbleSuite documented against a package it has moved out of.
    files = {**TREE}
    files.pop("internals/cli/suite_test.go")
    files["internals/cli/other_test.go"] = "package cli\n\nfunc TestOther() {}\n"
    r = run(run_check, files, battery())
    assert r["status"] == "fail"
    assert any(
        f["kind"] == "suite_in_package"
        and f["problem"] == "suite identifier not found anywhere in package"
        for f in r["evidence"]["verify_findings"]
    )


def test_fail_when_referenced_path_gone(run_check):
    files = {k: v for k, v in TREE.items() if k != "HACKING.md"}
    r = run(run_check, files, battery())
    assert r["status"] == "fail"
    assert any(
        f["kind"] == "path_exists" and f["path"] == "HACKING.md"
        for f in r["evidence"]["verify_findings"]
    )


def test_fail_when_text_in_file_pattern_missing(run_check):
    b = battery().replace(
        "      - kind: path_exists\n        path: HACKING.md\n",
        "      - kind: text_in_file\n        file: HACKING.md\n"
        "        pattern: no such text\n",
    )
    r = run(run_check, TREE, b)
    assert r["status"] == "fail"
    assert any(
        f["kind"] == "text_in_file" and f["problem"] == "pattern not found in file"
        for f in r["evidence"]["verify_findings"]
    )


def test_verify_none_is_reported_not_failed(run_check):
    b = battery().replace(
        "      - kind: path_exists\n        path: HACKING.md\n",
        "      - kind: none\n"
        "        reason: lives in GitHub settings, not the tree\n",
    )
    r = run(run_check, TREE, b)
    assert r["status"] == "pass"
    assert r["evidence"]["unanchored_entries"] == ["no-empty-interface"]


def test_schema_finding_when_ungated_entry_is_not_ci_verifiable(run_check):
    b = battery().replace(
        "    ci_verifiable: true\n  - id: no-empty-interface",
        "    ci_verifiable: false\n  - id: no-empty-interface",
    )
    r = run(run_check, TREE, b)
    assert r["status"] == "fail"
    assert any("gated_by" in f for f in r["evidence"]["schema_findings"])


def test_schema_finding_on_unknown_answer_grade(run_check):
    b = battery().replace("grade: command", "grade: vibes")
    r = run(run_check, TREE, b)
    assert r["status"] == "fail"
    assert any("answer.grade" in f for f in r["evidence"]["schema_findings"])


def test_fail_when_agents_md_absent_but_battery_present(run_check):
    files = {k: v for k, v in TREE.items() if k != "AGENTS.md"}
    r = run(run_check, files, battery())
    assert r["status"] == "fail"
    assert "no AGENTS.md" in r["summary"]


def test_digest_change_is_evidence_not_failure(run_check):
    # A changed AGENTS.md is a Layer 2 re-test trigger, not a defect — the file
    # may have improved. Surfaced as evidence, never as a fail on its own.
    files = {**TREE, "AGENTS.md": AGENTS_MD + "\nAn extra, harmless sentence.\n"}
    r = run(run_check, files, battery())
    assert r["status"] == "pass"
    assert r["evidence"]["agents_md_changed_since_seeding"] is True
