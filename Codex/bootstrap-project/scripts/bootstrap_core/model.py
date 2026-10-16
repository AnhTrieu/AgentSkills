from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import re
import tomllib
import jsonschema
from .util import BootstrapError, command, relative, within, sha, read_json

SKILL = Path(__file__).resolve().parents[2]
CATALOG = json.loads((SKILL / "assets/catalog/profiles.json").read_text())
CHECKS = ("format_check", "lint", "typecheck", "test", "build", "smoke")


def normalize(data, root):
    try:
        jsonschema.Draft202012Validator(
            json.loads((SKILL / "assets/schemas/project.schema.json").read_text())
        ).validate(data)
    except jsonschema.ValidationError as e:
        raise BootstrapError(
            "Manifest " + ".".join(map(str, e.absolute_path)) + ": " + e.message
        ) from e
    m = deepcopy(data)
    for key, default in {
        "sources": [],
        "decisions": [],
        "deviations": [],
        "overlays": [],
        "moves": [],
        "harnesses": ["claude_code", "codex", "antigravity"],
        "editor": {},
        "git": {},
        "remote": {},
        "ci": {},
        "infrastructure": {},
    }.items():
        m.setdefault(key, default)
    defaults = {
        "editor": {
            "enabled": True,
            "layout": "single_folder",
            "extension_installation": "recommend_only",
        },
        "git": {
            "initialize": True,
            "initial_branch": "main",
            "commit": "new_repo_after_verification",
            "additional_paths": [],
        },
        "remote": {"mode": "none", "push": False, "provider": "github", "visibility": "private"},
        "ci": {"provider": "github", "runner": "hosted"},
        "infrastructure": {"enabled": False, "devcontainer": False},
    }
    for k, vals in defaults.items():
        for key, v in vals.items():
            m[k].setdefault(key, v)
    if m["infrastructure"].get("provider"):
        raise BootstrapError(
            "Live infrastructure requires a separately installed provider adapter; see references/infrastructure.md"
        )
    if m["infrastructure"]["devcontainer"] and not m["infrastructure"]["enabled"]:
        raise BootstrapError("Dev container requires infrastructure.enabled=true")
    if m["remote"]["mode"] == "create" and not m["remote"].get("repository"):
        raise BootstrapError("Remote create requires owner/repository")
    if m["remote"]["mode"] == "link" and not m["remote"].get("url"):
        raise BootstrapError("Remote link requires url")
    if m["remote"].get("url") and not re.fullmatch(
        r"(https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?|git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)",
        m["remote"]["url"],
    ):
        raise BootstrapError("Use a credential-free GitHub HTTPS or SSH URL")
    ids = set()
    paths = set()
    components = []
    for i, c in enumerate(m["components"]):
        if c["id"] in ids:
            raise BootstrapError("Duplicate component id")
        ids.add(c["id"])
        c["path"] = relative(c["path"])
        within(root, c["path"])
        if c["path"].casefold() in paths:
            raise BootstrapError("Duplicate/case-colliding component path")
        paths.add(c["path"].casefold())
        profile = CATALOG["profiles"].get(c["profile"])
        if not profile:
            raise BootstrapError(
                "Unsupported profile: "
                + c["profile"]
                + "; use existing plus explicit commands or a requirement-backed overlay"
            )
        if c["profile"] != "existing":
            if (
                c["language"] not in profile["languages"]
                or c["package_manager"] not in profile["managers"]
            ):
                raise BootstrapError("Profile language/manager mismatch")
            if m["project"]["mode"] == "adopt":
                raise BootstrapError(
                    "Adoption must use profile=existing to preserve source and manifests"
                )
        c.setdefault(
            "name",
            m["project"]["name"]
            if len(m["components"]) == 1
            else m["project"]["name"] + "-" + c["id"].replace("_", "-"),
        )
        c.setdefault("import_name", c["name"].replace("-", "_"))
        c.setdefault("python_version", "3.12")
        c.setdefault("node_version", "24")
        c.setdefault("manager_version", "10.20.0" if c["package_manager"] == "pnpm" else "")
        c.setdefault("depends_on", [])
        c.setdefault("runtime_deps", [])
        c.setdefault("dev_deps", [])
        if c["language"] == "python" and not c["import_name"].isidentifier():
            raise BootstrapError("Invalid Python import name")
        c["runtime_label"] = (
            "Python " + c["python_version"]
            if c["language"] == "python"
            else "Node " + c["node_version"]
            if c["language"] in ("javascript", "typescript")
            else "project-defined"
        )
        c["commands"] = commands(c, root)
        components.append(c)
    if len(components) > 1 and "." in paths:
        raise BootstrapError("Multiple components must have separate non-overlapping directories")
    for a in paths:
        for b in paths:
            if a != b and b.startswith(a + "/"):
                raise BootstrapError("Component roots overlap")
    ordered = []
    pending = components[:]
    while pending:
        ready = [c for c in pending if set(c["depends_on"]) <= {x["id"] for x in ordered}]
        if not ready:
            raise BootstrapError("Component dependency cycle or unknown dependency")
        for c in ready:
            ordered.append(c)
            pending.remove(c)
    m["components"] = ordered
    for s in m["sources"]:
        from scan_project import is_secret

        if is_secret(s["path"]):
            raise BootstrapError("Private source document rejected")
        p = within(root, s["path"])
        if not p.is_file():
            raise BootstrapError("Missing source document: " + s["path"])
        h = sha(p.read_bytes())
        records = read_json(within(root, ".bootstrap/managed-files.json"), {}).get("files", {})
        record = records.get(s["path"], {})
        previous = read_json(within(root, ".bootstrap/project.json"), {}).get("sources", [])
        original = record.get("source_sha256") or next(
            (
                x.get("sha256")
                for x in previous
                if x["path"] == s["path"] and x["kind"] == s["kind"]
            ),
            None,
        )
        transformed = record.get("file_hash") == h and original
        if s.get("sha256") and s["sha256"] != h:
            if not transformed or original != s["sha256"]:
                raise BootstrapError("Source document changed: " + s["path"])
        elif not s.get("sha256"):
            s["sha256"] = original if transformed else h
    for p in m["git"]["additional_paths"]:
        within(root, p)
    if m["moves"] and m["project"]["mode"] != "reorganize":
        raise BootstrapError("Moves require reorganize mode")
    deviations = {d["id"] for d in m["deviations"]}
    for o in m["overlays"]:
        relative(o["path"])
        if o["deviation"] not in deviations:
            raise BootstrapError("Overlay lacks documented deviation: " + o["path"])
    for v in m["moves"]:
        relative(v["source"])
        relative(v["destination"])
        if v["source"] == v["destination"]:
            raise BootstrapError("Move source equals destination")
    return m


def commands(c, root):
    result = {}
    cwd = c["path"]
    manager = c["package_manager"]
    profile = c["profile"]
    new = profile != "existing"

    def add(k, argv, timeout=180):
        result[k] = command(c["id"] + ":" + k, argv, cwd, timeout)

    explicit = c.get("commands", {})
    if not new:
        p = within(root, cwd)
        if not p.is_dir():
            raise BootstrapError("Existing component is missing")
        if (p / "package.json").is_file():
            pkg = json.loads((p / "package.json").read_text())
            scripts = pkg.get("scripts", {})
            locks = {
                "pnpm-lock.yaml": "pnpm",
                "package-lock.json": "npm",
                "yarn.lock": "yarn",
                "bun.lock": "bun",
                "bun.lockb": "bun",
            }
            seen = {v for f, v in locks.items() if (p / f).exists()}
            if seen and seen != {manager}:
                raise BootstrapError("Existing lockfile/manager mismatch")
            for k, s in [
                ("lint", "lint"),
                ("typecheck", "typecheck"),
                ("test", "test"),
                ("build", "build"),
                ("dev", "dev"),
                ("format_check", "format:check"),
            ]:
                if s in scripts:
                    add(k, [manager, "run", s], 600 if k == "build" else 180)
        elif (p / "pyproject.toml").is_file():
            data = tomllib.loads((p / "pyproject.toml").read_text())
            seen = (
                "uv"
                if (p / "uv.lock").exists()
                else "poetry"
                if (p / "poetry.lock").exists()
                else None
            )
            if seen and seen != manager:
                raise BootstrapError("Existing Python manager mismatch")
            deps = (
                str(data.get("project", {}).get("dependencies", []))
                + str(data.get("dependency-groups", {}))
                + str(data.get("tool", {}).get("poetry", {}))
            )
            prefix = (
                ["uv", "run", "--no-sync"]
                if manager == "uv"
                else ["poetry", "run"]
                if manager == "poetry"
                else [".venv/bin/python", "-m"]
            )
            if "ruff" in deps:
                add("lint", prefix + ["ruff", "check", "."])
            if "pytest" in deps:
                add("test", prefix + ["pytest"])
    if c["language"] == "python":
        if manager == "uv":
            add("install", ["uv", "sync", "--dev"])
            add("ci_install", ["uv", "sync", "--locked", "--dev"])
            prefix = ["uv", "run", "--no-sync"]
            if new:
                defaults = ["ruff>=0.14,<1", "pytest>=8,<10"] + (
                    ["httpx>=0.28,<1"] if profile == "python.fastapi" else []
                )
                c["dev_deps"] = sorted(set(defaults + c["dev_deps"]))
                c["runtime_deps"] = sorted(
                    set(
                        c["runtime_deps"]
                        + (
                            ["fastapi>=0.115,<1", "uvicorn>=0.34,<1"]
                            if profile == "python.fastapi"
                            else []
                        )
                    )
                )
        elif manager == "poetry":
            if new:
                raise BootstrapError(
                    "Poetry greenfield templates are not shipped; use uv or adopt an existing Poetry project"
                )
            add("install", ["poetry", "install", "--no-interaction"])
            add("ci_install", ["poetry", "install", "--no-interaction"])
            prefix = ["poetry", "run"]
        elif manager == "pip":
            if new:
                raise BootstrapError(
                    "pip greenfield templates are not shipped; use uv or adopt existing requirements"
                )
            add("prepare", ["python3", "-m", "venv", ".venv"])
            req = (
                "requirements-dev.txt"
                if within(root, cwd + "/requirements-dev.txt").exists()
                else "requirements.txt"
            )
            if not within(root, cwd + "/" + req).exists():
                raise BootstrapError(
                    "pip adapter requires requirements.txt or requirements-dev.txt"
                )
            add("install", [".venv/bin/python", "-m", "pip", "install", "-r", req])
            add("ci_install", result["install"]["argv"])
            prefix = [".venv/bin/python", "-m"]
        elif not explicit:
            raise BootstrapError("Unknown manager needs explicit commands")
        if new:
            add("format_fix", prefix + ["ruff", "format", "src", "tests"])
            add("format_check", prefix + ["ruff", "format", "--check", "src", "tests"])
            add("lint", prefix + ["ruff", "check", "."])
            add("test", prefix + ["pytest"])
            add("build", ["uv", "build"], 300)
            if profile == "python.cli":
                add("dev", prefix + ["python", "-m", c["import_name"] + ".cli"])
            elif profile == "python.fastapi":
                add("dev", prefix + ["uvicorn", c["import_name"] + ".api:app", "--reload"])
    elif c["language"] in ("javascript", "typescript"):
        if manager == "pnpm":
            install = ["pnpm", "install"]
            ci = ["pnpm", "install", "--frozen-lockfile"]
        elif manager == "npm":
            install = ["npm", "install"]
            ci = ["npm", "ci"]
        elif manager == "yarn":
            text = (
                (within(root, cwd) / "yarn.lock").read_text()
                if (within(root, cwd) / "yarn.lock").exists()
                else ""
            )
            install = ["yarn", "install"]
            ci = install + (["--immutable"] if "__metadata:" in text else ["--frozen-lockfile"])
        elif manager == "bun":
            install = ["bun", "install"]
            ci = install + ["--frozen-lockfile"]
        else:
            raise BootstrapError("Unsupported JS manager")
        if new and manager not in ("pnpm", "npm"):
            raise BootstrapError(
                "New JS profiles support pnpm/npm; preserve other managers using existing"
            )
        add("install", install, 600)
        add("ci_install", ci, 600)
        if new:
            for k, s in [
                ("format_fix", "format"),
                ("format_check", "format:check"),
                ("lint", "lint"),
                ("test", "test"),
                ("build", "build"),
            ]:
                add(k, [manager, "run", s], 600 if k == "build" else 180)
            if c["language"] == "typescript":
                add("typecheck", [manager, "run", "typecheck"])
            if profile != "node.library":
                add("dev", [manager, "run", "dev"])
    for k, v in explicit.items():
        add(k, v["argv"], v.get("timeout", 180))
    if not new and not any(k in result for k in CHECKS):
        raise BootstrapError(
            "Existing/custom component needs at least one real verification command"
        )
    return result
