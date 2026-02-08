---
name: bootstrap-python-project
description: Bootstrap a complete greenfield Python package scaffold from user requirements, including packaging metadata, environment management, developer tooling, and automation. Use when users ask to start a new Python project/repo, generate starter files, set up UV or mini-conda environments, add pytest/lint/format/typecheck defaults, or produce a ready-to-run baseline layout.
---

# Bootstrap Python Project

Create a full, ready-to-use Python project scaffold in one pass. Prefer the generator script for deterministic output:

`python3 scripts/bootstrap_project.py "<project-name>" [options]`

## Workflow

1. Collect requirements from the user:
- Project name
- One-sentence description
- Project type: `general`, `data-science`, or `machine-learning`
- Python version (default `3.12`)
- Optional package/import name (default derived from project name)
- Optional output directory

2. Choose environment manager with this rule:
- Default to `UV`.
- If user specifies data science or machine learning, use `mini-conda`.
- If user explicitly asks for a manager, follow that request.

3. Run the scaffold generator:
- General/default project:
  `python3 scripts/bootstrap_project.py "my-project" --project-kind general --env-manager uv`
- Data science project:
  `python3 scripts/bootstrap_project.py "ml-lab" --project-kind machine-learning --env-manager mini-conda`

4. Verify generated files exist:
- `README.md`
- `pyproject.toml`
- `.gitignore`
- `justfile`
- `.githooks/pre-commit`
- `AGENTS.md`

5. Verify project shape and git bootstrap:
- `src/<package_name>/__init__.py`
- `src/<package_name>/__main__.py`
- `tests/test_smoke.py`
- `environment.yml` for mini-conda projects
- `.python-version` for UV projects
- `.git/` directory exists
- first commit exists and includes generated files
- `git config core.hooksPath` equals `.githooks`

6. Summarize what was generated and highlight next commands:
- UV: `just setup`, `just test`, `just run`
- mini-conda: `just setup`, then `just test`, `just run`
- mention repo is initialized, files are staged+committed, and hooks are installed via tracked `.githooks`

## Generator Options

- `--project-kind`: `general`, `data-science`, `machine-learning`
- `--env-manager`: `auto`, `uv`, `mini-conda`
- `--package-name`: override Python import package name
- `--python-version`: set base interpreter version
- `--output-dir`: create project outside current directory
- `--initial-commit-message`: override default first-commit message
- `--force`: overwrite generated files in a non-empty target directory

## Behavioral Requirements

- Always generate a standard Python package layout with `src/` and `tests/`.
- Always generate `pyproject.toml` with:
  - Package metadata
  - `pytest`, `ruff`, `black`, `mypy` in dev dependencies
  - Reasonable config blocks for pytest, Ruff, Black, and mypy
- Always generate a `justfile` with setup, run, test, lint, format, and typecheck commands.
- Always generate a tracked pre-commit hook at `.githooks/pre-commit` that runs formatter and lint commands for the selected stack.
- Always initialize git in the project root, configure `core.hooksPath` to `.githooks`, stage generated files, and create the first commit.
- Use default first commit message: `Initial project scaffold with environment setup, automation, and standard configs`, unless overridden via `--initial-commit-message`.
- If git identity is missing, use fallback identity for the first commit and warn users to configure `user.name`/`user.email`.
- Keep defaults pragmatic and minimal; add dependencies only when the user requests them.
- Preserve user-provided naming and description exactly where safe; normalize only filesystem/import identifiers.
