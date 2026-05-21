<!--
  Charm Tech CONTRIBUTING.md template.
  Copy into a repo and replace {{PROJECT}} (display name) and {{REPO}} (GitHub repo
  name). Add a project-specific intro and a Tests section describing how to run the
  project's tests. Extend with project-specific policies as needed.
-->
We welcome contributions to {{PROJECT}}!

Before working on changes, please consider [opening an issue](https://github.com/canonical/{{REPO}}/issues) explaining your use case. If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

# Pull requests

Changes are proposed as [pull requests on GitHub](https://github.com/canonical/{{REPO}}/pulls).

Pull requests should have a short title that follows the [conventional commit style](https://www.conventionalcommits.org/en/) using one of these types:

- chore
- ci
- docs
- feat
- fix
- perf
- refactor
- revert
- test

Some examples:

- feat: add the ability to observe change-updated events
- fix!: correct the type hinting for config data
- docs: clarify how to use mounts

We consider this project too small to use scopes, so we don't use them.

Note that the commit messages to the PR's branch do not need to follow the conventional commit format, as these will be squashed into a single commit to `main` using the PR title as the commit message.

To help us review your changes, please rebase your pull request onto the `main` branch before you request a review. If you need to bring in the latest changes from `main` after the review has started, please use a merge commit.

# Tests

Changes should include tests. <!-- Describe here how to run this project's tests. -->

# Coding style

We follow the Charm Tech team style guides:

- [Documentation and docstring style](https://github.com/canonical/charm-tech/blob/main/STYLE.md)
- [Python style](https://github.com/canonical/charm-tech/blob/main/python/STYLE.md)
- [Go style](https://github.com/canonical/charm-tech/blob/main/go/STYLE.md)

Most of this is enforced by CI checks.
