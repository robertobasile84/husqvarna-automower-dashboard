# Contributing

Thanks for your interest in improving the Automower Dashboard! This is a small
project, but contributions — bug reports, docs, features — are very welcome.

## Ground rules

- **`main` is protected.** All changes land through a pull request; direct pushes
  are not accepted. Open a PR from a topic branch (or a fork) and let CI run.
- **Be kind.** See the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Security issues are different** — please do *not* open a public issue. See
  [SECURITY.md](SECURITY.md).

## Development setup

The whole stack runs in Docker, so you don't strictly need a local Python. To run
it end-to-end with the collector built from your working tree:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
docker compose logs -f collector
```

With no credentials in `.env`, the collector runs in **demo mode** (synthetic
data) — perfect for iterating on the dashboard without a mower.

To work on the collector in Python directly (managed with [uv](https://docs.astral.sh/uv/)):

```bash
cd collector
uv sync                          # create .venv from the lockfile
uv run python probe.py --rest-only   # test API connectivity (needs real creds)
```

## Before you open a PR

CI runs these; run them locally first to get a green check:

```bash
cd collector
uvx ruff@0.8 check .            # lint
uvx ruff@0.8 format --check .   # formatting
```

If you changed dependencies, edit `collector/pyproject.toml`, run `uv lock`, and
commit both `pyproject.toml` and `uv.lock`.

## Commit & PR style

- Keep commits focused; write a clear imperative subject line ("Fix …", "Add …").
- Fill in the PR template — say what changed and how you verified it.
- Update docs (README, `docs/api-reference.md`) when behavior changes.
