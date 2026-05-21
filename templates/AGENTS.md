<!--
  Charm Tech AGENTS.md template.
  AGENTS.md gives AI agents project-specific guidance. Keep it short and concrete:
  agents read it on every task. Fill in each section for your project and delete
  this comment. (A symlink CLAUDE.md -> AGENTS.md keeps Claude Code in sync.)
-->
# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Project Overview

<!-- One or two sentences: what this project is and what it's for. -->

## Common Commands

```bash
# The handful of commands an agent will actually need. For example:
# make all          # Format, lint, and unit test (run before committing)
# make unit         # Unit tests
# make help         # See all available commands
```

## Code and Documentation Style

This project follows the Charm Tech team style guides. Read them if more
clarification is required:

- [Documentation and docstring style](https://github.com/canonical/charm-tech/blob/main/STYLE.md)
- [Python style](https://github.com/canonical/charm-tech/blob/main/python/STYLE.md) <!-- or -->
- [Go style](https://github.com/canonical/charm-tech/blob/main/go/STYLE.md)

Ensure that `pre-commit` is installed (with the user's permission) so that style
is enforced with every commit. If the user does not permit using `pre-commit`,
*always* ensure the lint/format/test command above shows no issues before committing.

Avoid writing prose documentation: that is a task for humans. When reviewing
documentation, pay particular attention to consistency with the style guides above.

## Architecture

<!-- The few things an agent can't easily infer: the main entry point, key
     modules, anything that must never be edited (e.g. generated code), and any
     invariants such as "always preserve backwards compatibility of the public API". -->

## Testing

<!-- Where tests live, how they're structured, unit vs integration, and any
     fixtures or markers an agent should know about. -->
