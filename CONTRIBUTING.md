# Contributing

Issues and pull requests are welcome in every public repository of this
organization. A record a verifier judges wrongly, a refusal you think is
mistaken, or a report a tool cannot read are the most useful contributions.
Include the bytes, or a command that reproduces them.

Report a security problem privately, as [SECURITY.md](SECURITY.md) describes,
not in an issue.

## Before you open a pull request

Each repository documents its own checks in its `README.md`, `CONTRIBUTING.md`
or `AGENTS.md`, and that file wins over this page. The usual set, from the
repository root:

```bash
uv sync --all-extras
uv run python -m pytest
python3 scripts/readme-lint.py README.md
```

Some repositories add a linter (`ruff check .`), a mutation check or a
workflow-steps gate. CI runs the same checks, so a green run on your branch is
the proof. A change that alters behavior comes with a test that fails without
it, and a fix for a reported bug adds that report's bytes as a test case.

## Commits

- Sign off every commit with the Developer Certificate of Origin:
  `git commit -s`. The sign-off line is `Signed-off-by: Your Name <you@example.com>`.
- Use conventional commits: `type(scope): subject`, where type is one of `feat`,
  `fix`, `docs`, `test`, `refactor`, `chore` or `perf`.
- Keep the subject under 72 characters, in the imperative mood, plain ASCII.
- Where a repository ships `.githooks`, run `git config core.hooksPath .githooks`
  once per clone so the same checks run before you push.

## Pull requests

One logical change per pull request. The title follows the same conventional
format as a commit subject. Describe what changed and how you checked it.
