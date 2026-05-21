# Charm Tech documentation style guide

This is the documentation and docstring style we use across Charm Tech projects,
regardless of the programming language. For language-specific code style, see
[python/STYLE.md](./python/STYLE.md) and [go/STYLE.md](./go/STYLE.md).

New docs should follow these guidelines, unless there's a good reason not to.
Sometimes existing docs don't follow these, but we're happy for them to be
updated to do so (either all at once, or as you change nearby text).

Of course, this is just a start! We add to this list as things come up in code
review; this list reflects our team decisions.

## Docs and docstrings

### Use British English

[Canonical's documentation style](https://docs.ubuntu.com/styleguide/en/) uses
British spelling, which we try to follow here. For example: "colour" rather than
"color", "labelled" rather than "labeled", "serialise" rather than "serialize",
and so on.

It's a bit less clear when we're dealing with code and APIs, as those normally
use US English, for example, `pytest.mark.parametrize`, and `color: #fff`.

### Spell out abbreviations

Abbreviations and acronyms in docstrings should usually be spelled out, for
example, "for example" rather than "e.g.", "that is" rather than "i.e.", "and so
on" rather than "etc", and "unit testing" rather than UT.

However, it's okay to use acronyms that are very well known in our domain, like
HTTP or JSON or RPC.

## How to write great documentation

- Use short sentences, ideally with one or two clauses.
- Use headings to split the doc into sections. Make sure that the purpose of
  each section is clear from its heading.
- Avoid a long introduction. Assume that the reader is only going to scan the
  first paragraph and the headings.
- Avoid background context unless it's essential for the reader to understand.

Recommended tone:

- Use a casual tone, but avoid idioms. Common contractions such as "it's" and
  "doesn't" are great.
- Use "we" to include the reader in what you're explaining.
- Avoid passive descriptions. If you expect the reader to do something, give a
  direct instruction.

Where docs are published, we organise the pages according to
[Diátaxis](https://diataxis.fr/) (tutorials, how-to guides, reference, and
explanation).
