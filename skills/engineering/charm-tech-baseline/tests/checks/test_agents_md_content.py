"""AGENTS.md content check: the five Layer 1 staleness checks."""
from __future__ import annotations

import textwrap


CLEAN = textwrap.dedent("""\
    # AGENTS.md

    See [HACKING.md](HACKING.md) for details. Tests use `gopkg.in/check.v1`.

    ## Build and test

    ```bash
    true --check          # lint gate
    false --lxd deploy    # deploys via LXD, needs juju
    ```
    """)


def test_na_when_agents_md_missing(run_check):
    r = run_check("agents-md-content", "canonical", {})
    assert r["status"] == "na"


def test_pass_when_content_clean(run_check):
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": CLEAN,
        "HACKING.md": "# Hacking\n",
    })
    assert r["status"] == "pass"
    assert r["evidence"]["runnable_failed"] == []
    assert r["evidence"]["missing_paths"] == []


def test_module_path_not_flagged_as_missing_file(run_check):
    # gopkg.in/check.v1 is a Go module path, not a local file — must not be
    # reported missing just because it contains a '/'.
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": CLEAN,
        "HACKING.md": "# Hacking\n",
    })
    assert "gopkg.in/check.v1" not in r["evidence"]["missing_paths"]


def test_environment_gated_command_not_executed(run_check):
    # `false` would fail if run; it must be classified environment-gated
    # (lxd/juju) and skipped, not executed — proven indirectly by the
    # overall check still passing (see test_pass_when_content_clean).
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": CLEAN,
        "HACKING.md": "# Hacking\n",
    })
    gated_commands = [g["command"] for g in r["evidence"]["environment_gated"]]
    assert any(c.startswith("false") for c in gated_commands)
    assert not any(rr["command"].startswith("false") for rr in r["evidence"]["runnable_failed"])


def test_fail_when_referenced_path_missing(run_check):
    md = textwrap.dedent("""\
        # AGENTS.md

        See [BOGUS.md](BOGUS.md) for details.
        """)
    r = run_check("agents-md-content", "canonical", {"AGENTS.md": md})
    assert r["status"] == "fail"
    assert "BOGUS.md" in r["evidence"]["missing_paths"]


def test_fail_when_command_tool_missing(run_check):
    md = textwrap.dedent("""\
        # AGENTS.md

        ```bash
        definitelynotarealbinary123 --check   # lint
        ```
        """)
    r = run_check("agents-md-content", "canonical", {"AGENTS.md": md})
    assert r["status"] == "fail"
    assert any(m["tool"] == "definitelynotarealbinary123" for m in r["evidence"]["missing_tools"])


def test_fail_when_runnable_command_fails(run_check):
    md = textwrap.dedent("""\
        # AGENTS.md

        ```bash
        false --check   # lint gate
        ```
        """)
    r = run_check("agents-md-content", "canonical", {"AGENTS.md": md})
    assert r["status"] == "fail"
    assert r["evidence"]["runnable_failed"]
    assert r["evidence"]["runnable_failed"][0]["command"].startswith("false")


def test_suite_not_found_in_package_flags_finding(run_check):
    # The canonical case: a gocheck suite documented against a package that
    # no longer contains it (pebble's PebbleSuite/cmd-pebble staleness).
    md = textwrap.dedent("""\
        # AGENTS.md

        ```bash
        go test ./internals/cli -check.f MySuite   # single suite
        ```
        """)
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": md,
        "internals/cli/other_test.go": "package cli\n\nfunc TestSomethingElse() {}\n",
    })
    findings = r["evidence"]["suite_findings"]
    assert any(f["suite"] == "MySuite" and f["problem"] == "suite identifier not found anywhere in package" for f in findings)


def test_suite_found_in_package_no_finding(run_check):
    md = textwrap.dedent("""\
        # AGENTS.md

        ```bash
        go test ./internals/cli -check.f MySuite   # single suite
        ```
        """)
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": md,
        "internals/cli/suite_test.go": "package cli\n\ntype MySuite struct{}\n",
    })
    assert r["evidence"]["suite_findings"] == []


def test_scope_lint_flags_harness_content(run_check):
    md = textwrap.dedent("""\
        # AGENTS.md

        Some guidance for agents.

        Co-Authored-By: Claude <noreply@example.invalid>
        """)
    r = run_check("agents-md-content", "canonical", {"AGENTS.md": md})
    assert r["status"] == "fail"
    assert r["evidence"]["scope_lint_findings"]


def test_version_pin_drift_flagged(run_check):
    md = "# AGENTS.md\n\nPinned tool: widget/cmd/widget@v1.0.0 (see CI).\n"
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": md,
        ".github/workflows/lint.yaml": "steps:\n  - run: go install widget/cmd/widget@v2.0.0\n",
    })
    assert r["status"] == "fail"
    assert r["evidence"]["version_drift"]
    assert r["evidence"]["version_drift"][0]["tool"] == "widget"
    assert r["evidence"]["version_drift"][0]["doc_version"] == "v1.0.0"
    assert r["evidence"]["version_drift"][0]["ci_versions"] == ["v2.0.0"]


def test_version_pin_matches_ci(run_check):
    md = "# AGENTS.md\n\nPinned tool: widget/cmd/widget@v1.0.0 (see CI).\n"
    r = run_check("agents-md-content", "canonical", {
        "AGENTS.md": md,
        ".github/workflows/lint.yaml": "steps:\n  - run: go install widget/cmd/widget@v1.0.0\n",
    })
    assert r["status"] == "pass"
    assert r["evidence"]["version_drift"] == []
    assert r["evidence"]["version_pins_checked"][0]["tool"] == "widget"
