#!/usr/bin/env python3
"""Read-only, stdlib-only inventory. Never executes project source."""

from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PRUNE = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    "dist",
    "build",
    ".tox",
    ".turbo",
}
LANG = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".swift": "swift",
    ".kt": "kotlin",
    ".rb": "ruby",
}
MANIFESTS = {
    "pyproject.toml",
    "requirements.txt",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "Package.swift",
    "pnpm-workspace.yaml",
}


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_info(root):
    def call(*args):
        try:
            r = subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    top = call("rev-parse", "--show-toplevel")
    return {
        "root": top,
        "is_root": bool(top and Path(top).resolve() == root.resolve()),
        "branch": call("branch", "--show-current") if top else None,
        "dirty": bool(call("status", "--porcelain")) if top else False,
        "staged": bool(call("diff", "--cached", "--name-only")) if top else False,
    }


def is_secret(rel):
    n = Path(rel).name.lower()
    if any(part in {".ssh", ".aws", ".gnupg"} for part in Path(rel).parts):
        return True
    if n in {".env.example", ".env.sample", ".env.template"}:
        return False
    return (
        n == ".env"
        or n.startswith(".env.")
        or n.endswith((".pem", ".key"))
        or n in {"credentials.json", "auth.json", "id_rsa", "id_ed25519"}
        or n.startswith("secrets.")
        or n in {"settings.local.json", ".pypirc", ".npmrc", "credentials"}
    )


def inventory(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Target must be an existing directory")
    files = []
    docs = []
    imports = []
    skipped = []
    local = set()
    for base, dirs, names in os.walk(root, followlinks=False):
        bp = Path(base)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in PRUNE
            and not (bp / d).is_symlink()
            and (bp / d).relative_to(root).as_posix() != ".bootstrap/local"
        )
        for n in sorted(names):
            p = bp / n
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                skipped.append({"path": rel, "reason": "symlink"})
                continue
            if is_secret(rel):
                skipped.append({"path": rel, "reason": "private configuration"})
                continue
            size = p.stat().st_size
            if size > 2_000_000:
                skipped.append({"path": rel, "reason": "large file"})
                continue
            lang = LANG.get(p.suffix.lower())
            kind = "unknown"
            if n in MANIFESTS:
                kind = "manifest"
            elif rel.startswith(
                (".vscode/", ".claude/", ".codex/", ".agents/", ".agent/")
            ) or n.endswith(".code-workspace"):
                kind = "workspace"
            elif rel.startswith(".github/") or n == ".gitlab-ci.yml":
                kind = "ci"
            elif n in {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}:
                kind = "instructions"
            elif p.suffix.lower() in {".md", ".rst"} or n.startswith(
                ("README", "LICENSE", "CHANGELOG")
            ):
                kind = "document"
                docs.append(rel)
            elif lang:
                kind = (
                    "test"
                    if (
                        n.startswith("test_")
                        or ".test." in n
                        or "tests" in p.relative_to(root).parts
                        or n == "conftest.py"
                    )
                    else "source"
                )
            elif p.suffix.lower() in {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg"}:
                kind = "configuration"
            files.append(
                {"path": rel, "kind": kind, "language": lang, "sha256": digest(p), "size": size}
            )
            if lang == "python":
                local.add(p.stem)
                for parent in p.relative_to(root).parts[:-1]:
                    local.add(parent)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for f in files:
        if f["language"] != "python":
            continue
        try:
            tree = ast.parse((root / f["path"]).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [x.name.split(".")[0] for x in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                if n not in stdlib | local:
                    imports.append(
                        {"import": n, "path": f["path"], "usage": f["kind"], "distribution": None}
                    )
    return {
        "schema_version": 1,
        "root": str(root),
        "git": git_info(root),
        "files": files,
        "docs_to_read": docs,
        "imports": imports,
        "skipped": skipped,
        "languages": sorted({f["language"] for f in files if f["language"]}),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(inventory(sys.argv[1]), indent=2))
    except (IndexError, ValueError, OSError) as e:
        print(json.dumps({"status": "failed", "error": str(e)}))
        sys.exit(2)
