#!/usr/bin/env python3
"""Generate a complete greenfield Python project scaffold."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

DEFAULT_INITIAL_COMMIT_MESSAGE = (
    "Initial project scaffold with environment setup, automation, and standard configs"
)

FALLBACK_GIT_NAME = "Project Scaffold Bot"
FALLBACK_GIT_EMAIL = "scaffold@local.invalid"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def normalize_package_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not name:
        raise ValueError("Package name is empty after normalization.")
    if name[0].isdigit():
        name = f"pkg_{name}"
    return name


def resolve_env_manager(project_kind: str, env_manager: str) -> str:
    if env_manager != "auto":
        return env_manager
    if project_kind in {"data-science", "machine-learning"}:
        return "mini-conda"
    return "uv"


def target_version_tag(python_version: str) -> str:
    parts = python_version.split(".")
    if len(parts) < 2:
        return "py312"
    return f"py{parts[0]}{parts[1]}"


def render_readme(
    project_name: str,
    package_name: str,
    description: str,
    env_manager: str,
    conda_env_name: str,
    python_version: str,
) -> str:
    if env_manager == "uv":
        setup = """```bash
just setup
just test
just run
```

Equivalent commands:

```bash
uv sync --extra dev
uv run pytest
uv run python -m PACKAGE_NAME
```"""
    else:
        setup = f"""```bash
just setup
just test
just run
```

Equivalent commands:

```bash
conda env create -f environment.yml
conda run -n {conda_env_name} pytest
conda run -n {conda_env_name} python -m PACKAGE_NAME
```"""

    readme = f"""# {project_name}

{description}

## Requirements

- Python {python_version}+
- `just` command runner
- {"UV (`uv`)" if env_manager == "uv" else "mini-conda (`conda`)"} installed

## Quick Start

{setup}

## Project Layout

- `src/{package_name}/`: package source code
- `tests/`: test suite
- `pyproject.toml`: package metadata and tool configuration
- `justfile`: common development commands
- `AGENTS.md`: agent integration and extension notes
"""

    return readme.replace("PACKAGE_NAME", package_name).strip() + "\n"


def render_gitignore(env_manager: str) -> str:
    manager_lines = (
        ".venv/\nuv.lock\n.python-version"
        if env_manager == "uv"
        else ".conda/\nenvironment.local.yml"
    )
    return (
        f"""# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Unit test / coverage reports
.coverage
.coverage.*
.pytest_cache/
.ruff_cache/
.mypy_cache/
htmlcov/
.hypothesis/

# Jupyter
.ipynb_checkpoints/

# IDEs
.idea/
.vscode/

# OS artifacts
.DS_Store
Thumbs.db

# Environment manager
{manager_lines}
"""
    ).strip() + "\n"


def render_pyproject(
    project_name: str,
    package_name: str,
    description: str,
    python_version: str,
) -> str:
    py_tag = target_version_tag(python_version)
    return (
        dedent(
            f"""
            [build-system]
            requires = ["hatchling>=1.24.0"]
            build-backend = "hatchling.build"

            [project]
            name = "{project_name}"
            version = "0.1.0"
            description = "{description}"
            readme = "README.md"
            requires-python = ">={python_version}"
            dependencies = []

            [project.optional-dependencies]
            dev = [
              "pytest>=8.0",
              "ruff>=0.6.0",
              "black>=24.0.0",
              "mypy>=1.10.0",
            ]

            [tool.hatch.build.targets.wheel]
            packages = ["src/{package_name}"]

            [tool.pytest.ini_options]
            minversion = "8.0"
            addopts = "-ra -q"
            testpaths = ["tests"]

            [tool.ruff]
            line-length = 100
            src = ["src", "tests"]
            target-version = "{py_tag}"

            [tool.ruff.lint]
            select = ["E", "F", "I", "B", "UP", "N"]

            [tool.black]
            line-length = 100
            target-version = ["{py_tag}"]

            [tool.mypy]
            python_version = "{python_version}"
            strict = true
            files = ["src", "tests"]
            warn_unused_configs = true

            [[tool.mypy.overrides]]
            module = ["tests.*"]
            disallow_untyped_defs = false
            """
        ).strip()
        + "\n"
    )


def render_justfile(env_manager: str, package_name: str, conda_env_name: str) -> str:
    if env_manager == "uv":
        return (
            dedent(
                f"""
                set shell := ["bash", "-cu"]

                default:
                    @just --list

                setup:
                    uv sync --extra dev
                    just install-hooks

                test:
                    uv run pytest

                lint:
                    uv run ruff check .

                format:
                    uv run black .

                format-check:
                    uv run black --check .

                typecheck:
                    uv run mypy src tests

                run:
                    uv run python -m {package_name}

                check:
                    just lint
                    just format-check
                    just typecheck
                    just test

                add dep:
                    uv add {{{{dep}}}}

                add-dev dep:
                    uv add --optional dev {{{{dep}}}}

                install-hooks:
                    git config core.hooksPath .githooks
                """
            ).strip()
            + "\n"
        )

    return (
        dedent(
            f"""
            set shell := ["bash", "-cu"]
            env_name := "{conda_env_name}"

            default:
                @just --list

            setup:
                conda env create -f environment.yml || conda env update -f environment.yml --prune
                just install-hooks

            test:
                conda run -n {{{{env_name}}}} pytest

            lint:
                conda run -n {{{{env_name}}}} ruff check .

            format:
                conda run -n {{{{env_name}}}} black .

            format-check:
                conda run -n {{{{env_name}}}} black --check .

            typecheck:
                conda run -n {{{{env_name}}}} mypy src tests

            run:
                conda run -n {{{{env_name}}}} python -m {package_name}

            check:
                just lint
                just format-check
                just typecheck
                just test

            update-env:
                conda env update -f environment.yml --prune

            install-hooks:
                git config core.hooksPath .githooks
            """
        ).strip()
        + "\n"
    )


def render_pre_commit_hook(env_manager: str, conda_env_name: str) -> str:
    if env_manager == "uv":
        body = """if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to run pre-commit checks." >&2
    exit 1
fi

uv run black .
uv run ruff check ."""
    else:
        body = f"""if ! command -v conda >/dev/null 2>&1; then
    echo "conda is required to run pre-commit checks." >&2
    exit 1
fi

conda run -n {conda_env_name} black .
conda run -n {conda_env_name} ruff check ."""

    return f"""#!/usr/bin/env bash
set -euo pipefail

{body}
"""


def render_agents_md(project_name: str) -> str:
    return (
        dedent(
            f"""
            # AGENTS

            ## Purpose
            Document agent integrations, responsibilities, and extension points for `{project_name}`.

            ## Agent Integrations
            - Name:
            - Trigger:
            - Inputs:
            - Outputs:
            - Failure handling:

            ## Extension Points
            - Data providers:
            - Service clients:
            - CLI commands:
            - Scheduled tasks:

            ## Operational Guardrails
            - Run `just lint`, `just typecheck`, and `just test` before proposing code changes.
            - Keep external side effects explicit and reversible.
            - Log assumptions in pull requests or task notes.

            ## Ownership
            - Primary maintainer:
            - Backup maintainer:
            - Escalation path:
            """
        ).strip()
        + "\n"
    )


def render_package_init() -> str:
    return (
        dedent(
            '''
            """Top-level package for the project."""

            __all__ = ["hello", "__version__"]
            __version__ = "0.1.0"


            def hello() -> str:
                return "Hello from your new project scaffold."
            '''
        ).strip()
        + "\n"
    )


def render_package_main(package_name: str) -> str:
    return (
        dedent(
            f'''
            """CLI entry point for `{package_name}`."""

            from {package_name} import hello


            def main() -> None:
                print(hello())


            if __name__ == "__main__":
                main()
            '''
        ).strip()
        + "\n"
    )


def render_smoke_test(package_name: str) -> str:
    return (
        dedent(
            f"""
            from {package_name} import hello


            def test_hello_smoke() -> None:
                assert "Hello" in hello()
            """
        ).strip()
        + "\n"
    )


def render_environment_yml(conda_env_name: str, python_version: str) -> str:
    return (
        dedent(
            f"""
            name: {conda_env_name}
            channels:
              - conda-forge
            dependencies:
              - python={python_version}
              - pip
              - pip:
                  - -e ".[dev]"
            """
        ).strip()
        + "\n"
    )


def write_file(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(
            f"{path} already exists. Re-run with --force to overwrite generated files."
        )
    path.write_text(content, encoding="utf-8")


def ensure_git_available() -> None:
    if shutil.which("git") is None:
        raise SystemExit(
            "Git is required but was not found in PATH. Install git and re-run the scaffold command."
        )


def run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        details = stderr or stdout or "No output captured."
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{details}")
    return result


def git_value(project_dir: Path, key: str) -> str:
    result = run_git(["config", "--get", key], cwd=project_dir, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def bootstrap_git_repo(project_dir: Path, commit_message: str) -> bool:
    run_git(["init"], cwd=project_dir)
    run_git(["config", "core.hooksPath", ".githooks"], cwd=project_dir)
    run_git(["add", "."], cwd=project_dir)

    user_name = git_value(project_dir, "user.name")
    user_email = git_value(project_dir, "user.email")
    used_fallback_identity = not (user_name and user_email)

    commit_args = ["commit", "--no-verify", "-m", commit_message]
    if used_fallback_identity:
        commit_args = [
            "-c",
            f"user.name={FALLBACK_GIT_NAME}",
            "-c",
            f"user.email={FALLBACK_GIT_EMAIL}",
            *commit_args,
        ]

    run_git(commit_args, cwd=project_dir)
    return used_fallback_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_name", help="Project name. Used as distribution name by default.")
    parser.add_argument(
        "--description",
        default="A new Python package.",
        help="One-line project description.",
    )
    parser.add_argument(
        "--package-name",
        help="Python import package name. Defaults to normalized project name.",
    )
    parser.add_argument(
        "--python-version",
        default="3.12",
        help="Minimum supported Python version (default: 3.12).",
    )
    parser.add_argument(
        "--project-kind",
        choices=["general", "data-science", "machine-learning"],
        default="general",
        help="Project category used for environment manager defaults.",
    )
    parser.add_argument(
        "--env-manager",
        choices=["auto", "uv", "mini-conda"],
        default="auto",
        help="Use auto to pick UV by default and mini-conda for DS/ML projects.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory where the project folder will be created.",
    )
    parser.add_argument(
        "--initial-commit-message",
        default=DEFAULT_INITIAL_COMMIT_MESSAGE,
        help="Commit message used for the first git commit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite generated files if they already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_slug = slugify(args.project_name)
    if not project_slug:
        raise SystemExit("Project name did not contain usable characters.")
    ensure_git_available()

    package_name = normalize_package_name(args.package_name or project_slug)
    env_manager = resolve_env_manager(args.project_kind, args.env_manager)
    conda_env_name = f"{project_slug.replace('-', '_')}_dev"

    project_dir = Path(args.output_dir).expanduser().resolve() / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)

    if any(project_dir.iterdir()) and not args.force:
        raise SystemExit(
            f"Target directory is not empty: {project_dir}. Re-run with --force to overwrite generated files."
        )

    files = {
        "README.md": render_readme(
            project_name=args.project_name,
            package_name=package_name,
            description=args.description,
            env_manager=env_manager,
            conda_env_name=conda_env_name,
            python_version=args.python_version,
        ),
        "pyproject.toml": render_pyproject(
            project_name=project_slug,
            package_name=package_name,
            description=args.description,
            python_version=args.python_version,
        ),
        ".gitignore": render_gitignore(env_manager),
        "justfile": render_justfile(env_manager, package_name, conda_env_name),
        ".githooks/pre-commit": render_pre_commit_hook(env_manager, conda_env_name),
        "AGENTS.md": render_agents_md(args.project_name),
        f"src/{package_name}/__init__.py": render_package_init(),
        f"src/{package_name}/__main__.py": render_package_main(package_name),
        "tests/test_smoke.py": render_smoke_test(package_name),
    }

    if env_manager == "uv":
        files[".python-version"] = f"{args.python_version}\n"
    else:
        files["environment.yml"] = render_environment_yml(conda_env_name, args.python_version)

    written_paths: list[Path] = []
    for rel_path, content in files.items():
        destination = project_dir / rel_path
        write_file(destination, content, force=args.force)
        written_paths.append(destination)

    hook_path = project_dir / ".githooks" / "pre-commit"
    hook_path.chmod(0o755)

    try:
        used_fallback_identity = bootstrap_git_repo(
            project_dir=project_dir, commit_message=args.initial_commit_message
        )
    except RuntimeError as err:
        raise SystemExit(str(err))

    print(f"Created project scaffold: {project_dir}")
    print(f"Environment manager: {env_manager}")
    print("Initialized git repository with an initial commit.")
    if used_fallback_identity:
        print(
            "Warning: git user.name/email were not configured. "
            "Used fallback identity for the initial commit. "
            "Set your identity with: git config --global user.name \"Your Name\" "
            "and git config --global user.email \"you@example.com\""
        )
    print("Generated files:")
    for path in sorted(written_paths):
        print(f"- {path.relative_to(project_dir)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
