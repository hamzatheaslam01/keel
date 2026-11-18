# T-05: CI workflow and repo hygiene

## Goal
Add a GitHub Actions workflow that runs ruff and pytest on every push, plus `.gitignore` and the MIT `LICENSE`.

## Context
The project uses uv with a `dev` dependency group (pytest, pytest-asyncio, respx, ruff). The free GitHub Actions tier is used. Run outputs go in `results/`, which is gitignored except for published runs (folders named `published-*`). Local model files live in `models/`. The user's local `keel.yaml` may hold API keys, so it is ignored; `keel.example.yaml` is committed.

## Files
Create:
- `.github/workflows/ci.yml`
- `.gitignore`
- `LICENSE`

Read: `pyproject.toml`.

## Implement
1. `ci.yml`: name `ci`; `on: [push, pull_request]`; one job `test` on `ubuntu-latest` with these steps:
   - `actions/checkout@v4`
   - `astral-sh/setup-uv@v5` with `python-version: "3.11"`
   - `uv sync --group dev`
   - `uv run ruff check .`
   - `uv run pytest -q -m "not perf"`

   The `perf` marker is registered later (T-34). Until then `-m "not perf"` selects everything.
2. `.gitignore` entries: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `*.db`, `*.db-wal`, `*.db-shm`, `models/`, `keel.yaml`, `results/*`, `!results/published-*/`, `!results/.gitkeep`, `viewer/node_modules/`, `viewer/.next/`, `.env`.
3. `results/.gitkeep`: an empty file.
4. `LICENSE`: the standard MIT text, `Copyright (c) 2026 Hamza Aslam`.

## Tests
No pytest file. Validation is via the Acceptance commands.

## Acceptance
```bash
uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); assert 'test' in d['jobs']; print('ok')"
uv run ruff check .
uv run python -c "t=open('.gitignore').read(); assert 'keel.yaml' in t and 'models/' in t; print('ok')"
```
Each python command prints `ok`.

## Out of scope
Python source, Docker (T-37), and release workflows.

## Depends on
T-01

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
