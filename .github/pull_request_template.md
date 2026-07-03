## What & why

<!-- What does this PR change, and what problem does it solve? Link any issue: Closes #123 -->

## How I verified

<!-- e.g. ran the stack in demo mode, checked the dashboard, ran probe.py against a real mower, ran `uvx ruff check .` -->

## Checklist

- [ ] `uvx ruff@0.8 check .` and `uvx ruff@0.8 format --check .` pass (in `collector/`)
- [ ] Docs updated if behavior changed (README / `docs/api-reference.md`)
- [ ] No secrets (credentials, tokens) committed
- [ ] If deps changed: `uv lock` run and `uv.lock` committed
