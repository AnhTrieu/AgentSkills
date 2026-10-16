from __future__ import annotations
import json
import shlex
import tomllib
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from .model import SKILL, CATALOG
from .util import BootstrapError, relative

ENV = Environment(
    loader=FileSystemLoader(SKILL / "assets/templates"),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
ENV.filters.update(
    json=lambda v: json.dumps(v, ensure_ascii=False, indent=2),
    shell=shlex.join,
    yaml=lambda v: yaml.safe_dump(v, sort_keys=False, allow_unicode=True),
)


def render(m, raw):
    outputs = {}
    ctx = dict(m)

    def put(path, content, policy="file", owner="common"):
        path = relative(path)
        if path in outputs:
            raise BootstrapError("Multiple output producers: " + path)
        outputs[path] = {
            "content": content if content.endswith("\n") else content + "\n",
            "policy": policy,
            "owner": owner,
        }

    def template(path, t, extra=None, policy="file", owner="common"):
        put(path, ENV.get_template(t).render(**(ctx | (extra or {}))), policy, owner)

    def j(path, value, policy="file", owner="common"):
        template(path, "common/json.j2", {"value": value}, policy, owner)

    template("README.md", "common/README.md.j2", policy="block")
    template("AGENTS.md", "common/AGENTS.md.j2", policy="block")
    template("docs/bootstrap-decisions.md", "common/decisions.md.j2", policy="block")
    template(".gitignore", "common/gitignore.j2", policy="ignore")
    template(".editorconfig", "common/editorconfig.j2")
    j(".bootstrap/project.json", raw)
    for c in m["components"]:
        if c["profile"] == "existing":
            continue
        prefix = "" if c["path"] == "." else c["path"] + "/"
        ex = {
            "c": c,
            "ts": c["language"] == "typescript",
            "ext": "ts" if c["language"] == "typescript" else "js",
            "jsxext": "tsx" if c["language"] == "typescript" else "jsx",
        }

        def t(p, name):
            template(prefix + p, name, ex, owner=c["id"])

        def cj(p, data):
            j(prefix + p, data, owner=c["id"])

        if c["language"] == "python":
            t("pyproject.toml", "python/pyproject.toml.j2")
            put(prefix + ".python-version", c["python_version"], owner=c["id"])
            t("src/" + c["import_name"] + "/__init__.py", "python/init.py.j2")
            name = {"python.library": "core", "python.cli": "cli", "python.fastapi": "api"}[
                c["profile"]
            ]
            t(
                "src/" + c["import_name"] + "/" + name + ".py",
                "python/" + ("library" if name == "core" else name) + ".py.j2",
            )
            t("tests/test_entrypoint.py", "python/test.py.j2")
        else:
            render_node(c, ex, t, cj, put, prefix)
    if (
        m["project"]["mode"] == "init"
        and len(m["components"]) > 1
        and all(c["package_manager"] == "pnpm" for c in m["components"])
    ):
        versions = {c["manager_version"] for c in m["components"]}
        if len(versions) != 1:
            raise BootstrapError("pnpm workspace requires a single manager version")
        j(
            "package.json",
            {
                "name": m["project"]["name"],
                "private": True,
                "packageManager": "pnpm@" + next(iter(versions)),
            },
        )
        template(
            "pnpm-workspace.yaml",
            "common/yaml.j2",
            {"value": {"packages": [c["path"] for c in m["components"]]}},
        )
    if len(m["components"]) > 1:
        for c in m["components"]:
            template(
                c["path"] + "/AGENTS.md",
                "common/AGENTS.md.j2",
                {"components": [c]},
                policy="block",
                owner=c["id"],
            )
    if m["editor"]["enabled"]:
        render_editor(m, j)
    if m["harnesses"]:
        template(".agents/skills/verify-project/SKILL.md", "harness/verify-project.md.j2")
    if "claude_code" in m["harnesses"]:
        template("CLAUDE.md", "harness/CLAUDE.md.j2", policy="block")
        template(".claude/skills/verify-project/SKILL.md", "harness/verify-project.md.j2")
        if len(m["components"]) > 1:
            for c in m["components"]:
                template(c["path"] + "/CLAUDE.md", "harness/CLAUDE.md.j2", policy="block")
    if "codex" in m["harnesses"]:
        template(".codex/config.toml", "harness/codex.toml.j2", policy="preserve")
    if m["ci"]["provider"] != "none":
        from .integrations import ci_config

        path, value = ci_config(m)
        template(path, "ci/workflow.yml.j2", {"value": value}, policy="preserve")
    if m["infrastructure"]["enabled"] and m["infrastructure"]["devcontainer"]:
        inf = m["infrastructure"]
        features = {}
        if any(c["language"] == "python" for c in m["components"]):
            features["ghcr.io/devcontainers/features/python:1"] = {
                "version": next(
                    c["python_version"] for c in m["components"] if c["language"] == "python"
                )
            }
        if any(c["language"] in ("javascript", "typescript") for c in m["components"]):
            features["ghcr.io/devcontainers/features/node:1"] = {
                "version": next(
                    c["node_version"]
                    for c in m["components"]
                    if c["language"] in ("javascript", "typescript")
                )
            }
        j(
            ".devcontainer/devcontainer.json",
            {
                "name": m["project"]["name"],
                "image": inf.get("image", "mcr.microsoft.com/devcontainers/base:ubuntu-24.04"),
                "features": features,
                "forwardPorts": inf.get("ports", []),
                "customizations": {"vscode": {"extensions": extension_ids(m)}},
                "postCreateCommand": container_setup(m),
            },
        )
    for overlay in m["overlays"]:
        path = relative(overlay["path"])
        if path.startswith(".bootstrap/"):
            raise BootstrapError("Overlays cannot replace bootstrap metadata")
        outputs[path] = {
            "content": overlay["content"],
            "policy": "file",
            "owner": "deviation:" + overlay["deviation"],
        }
    for path, item in outputs.items():
        try:
            if path.endswith(".json") or path.endswith(".code-workspace"):
                json.loads(item["content"])
            elif path.endswith(".toml"):
                tomllib.loads(item["content"])
            elif path.endswith((".yml", ".yaml")):
                yaml.safe_load(item["content"])
            elif path.endswith(".py"):
                compile(item["content"], path, "exec")
        except Exception as e:
            raise BootstrapError("Invalid rendered " + path + ": " + str(e)) from e
    return outputs


def render_node(c, ex, t, j, put, prefix):
    ts = ex["ts"]
    ext = ex["ext"]
    jsx = ex["jsxext"]
    p = c["profile"]
    versions = CATALOG["node_defaults"]
    deps = {}
    dev = {k: versions[k] for k in ["eslint", "@eslint/js", "globals", "prettier"]}
    if ts:
        dev.update(
            {k: versions[k] for k in ["typescript", "tsx", "@types/node", "typescript-eslint"]}
        )
    web = p.startswith("web.")
    src = "app" if p == "web.nextjs" else "src"
    scripts = {
        "format": f"prettier --write {src} tests",
        "format:check": f"prettier --check {src} tests",
        "lint": f"eslint {src} tests",
        "test": (
            "node --import tsx --test tests/*.test.mjs"
            if web
            else "node --import tsx --test tests/*.test.ts"
            if ts
            else "node --test tests/*.test.js"
        ),
    }
    if ts:
        scripts["typecheck"] = (
            "next typegen && tsc --noEmit" if p == "web.nextjs" else "tsc --noEmit"
        )
    if not web:
        entry = "index" if p == "node.library" else "cli" if p == "node.cli" else "server"
        scripts["build"] = "tsc" if ts else f"node --check src/{entry}.js"
        if p != "node.library":
            scripts["dev"] = f"tsx src/{entry}.ts" if ts else f"node src/{entry}.js"
        if p in ("node.express", "node.fastify"):
            framework = p.split(".")[1]
            deps[framework] = versions[framework]
            if ts and framework == "express":
                dev["@types/express"] = versions["@types/express"]
            t("src/app." + ext, "node/api.j2")
            t("src/server." + ext, "node/server.j2")
        else:
            t(
                "src/" + entry + "." + ext,
                "node/" + ("index" if p == "node.library" else "cli") + ".j2",
            )
        t("tests/entrypoint.test." + ext, "node/test.j2")
    else:
        deps.update({k: versions[k] for k in ["react", "react-dom"]})
        dev["tsx"] = versions["tsx"]
        dev["eslint-plugin-react"] = "^7.37.5"
        if ts:
            dev.update({k: versions[k] for k in ["@types/react", "@types/react-dom"]})
        if p == "web.react-vite":
            dev["vite"] = versions["vite"]
            scripts.update(dev="vite --host 127.0.0.1", build="vite build")
            t("index.html", "web/index.html.j2")
            t("src/App." + jsx, "web/app.j2")
            t("src/main." + jsx, "web/main.j2")
            put(
                prefix + "vite.config.mjs",
                "export default { esbuild: { jsx: 'automatic' } };\n",
                owner=c["id"],
            )
            test = (
                "import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport React from 'react';\nimport { renderToStaticMarkup } from 'react-dom/server';\nimport App from '../src/App."
                + jsx
                + "';\ntest('renders project heading', () => {\n  assert.ok(renderToStaticMarkup(React.createElement(App)).includes("
                + json.dumps(c["name"])
                + "));\n});\n"
            )
        else:
            deps["next"] = versions["next"]
            scripts.update(dev="next dev --hostname 127.0.0.1", build="next build")
            t("app/page." + jsx, "web/app.j2")
            t("app/layout." + jsx, "web/layout.j2")
            t("app/api/health/route." + ext, "web/health.j2")
            if ts:
                put(
                    prefix + "next-env.d.ts",
                    '/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n',
                    owner=c["id"],
                )
            test = (
                "import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport { GET } from '../app/api/health/route."
                + ext
                + "';\ntest('health route', async () => {\n  const r = await GET();\n  assert.equal(r.status, 200);\n  assert.deepEqual(await r.json(), { status: 'ok' });\n});\n"
            )
        put(prefix + "tests/entrypoint.test.mjs", test, owner=c["id"])
    deps.update(c.get("npm_dependencies", {}))
    dev.update(c.get("npm_dev_dependencies", {}))
    package = {
        "name": c["name"],
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "engines": {"node": ">=22.12"},
        "scripts": scripts,
        "dependencies": deps,
        "devDependencies": dev,
    }
    if c["manager_version"]:
        package["packageManager"] = c["package_manager"] + "@" + c["manager_version"]
    if p == "node.library":
        package["exports"] = "./dist/index.js" if ts else "./src/index.js"
    if p == "node.cli":
        package["bin"] = {c["name"]: "./dist/cli.js" if ts else "./src/cli.js"}
    j("package.json", package)
    j(".prettierrc.json", {"singleQuote": True, "printWidth": 100})
    t(".prettierignore", "node/prettierignore.j2")
    t("eslint.config.mjs", "node/eslint.j2")
    put(prefix + ".node-version", c["node_version"] + "\n", owner=c["id"])
    if ts or web:
        opts = {"target": "ES2022", "strict": True, "skipLibCheck": True, "esModuleInterop": True}
        if web:
            opts.update(
                module="ESNext",
                moduleResolution="Bundler",
                jsx="react-jsx",
                noEmit=True,
                lib=["DOM", "ES2022"],
                allowJs=not ts,
            )
        else:
            opts.update(
                module="NodeNext",
                moduleResolution="NodeNext",
                outDir="dist",
                rootDir="src",
                declaration=True,
            )
        if p == "web.nextjs":
            opts.update(plugins=[{"name": "next"}], resolveJsonModule=True, isolatedModules=True)
        j(
            "tsconfig.json" if ts else "jsconfig.json",
            {
                "compilerOptions": opts,
                "include": (
                    ["next-env.d.ts", "app/**/*", ".next/types/**/*.ts"]
                    if p == "web.nextjs"
                    else ["src/**/*"]
                ),
                "exclude": ["node_modules", "dist"],
            },
        )


def extension_ids(m):
    ids = set()
    for c in m["components"]:
        if c["language"] == "python":
            ids.update(["ms-python.python", "ms-python.vscode-pylance", "ms-python.debugpy"])
            if "ruff" in str(c["commands"]):
                ids.add("charliermarsh.ruff")
        elif c["language"] in ("javascript", "typescript"):
            if "lint" in c["commands"]:
                ids.add("dbaeumer.vscode-eslint")
            if "format_check" in c["commands"]:
                ids.add("esbenp.prettier-vscode")
    return sorted(ids)


def render_editor(m, j):
    tasks = []
    launches = []
    multi = m["editor"]["layout"] == "multi_root" and len(m["components"]) > 1
    base = "${workspaceFolder:repository}" if multi else "${workspaceFolder}"
    ids = extension_ids(m)
    for c in m["components"]:
        cwd = base if c["path"] == "." else base + "/" + c["path"]
        for key, cmd in c["commands"].items():
            if key in ("ci_install", "lock"):
                continue
            tasks.append(
                {
                    "label": c["id"] + ":" + key,
                    "type": "process",
                    "command": cmd["argv"][0],
                    "args": cmd["argv"][1:],
                    "options": {"cwd": cwd},
                    "problemMatcher": [],
                }
            )
        if c["profile"] == "python.cli":
            launches.append(
                {
                    "name": c["id"],
                    "type": "debugpy",
                    "request": "launch",
                    "module": c["import_name"] + ".cli",
                    "cwd": cwd,
                    "python": cwd + "/.venv/bin/python",
                }
            )
        elif c["profile"] == "python.fastapi":
            launches.append(
                {
                    "name": c["id"],
                    "type": "debugpy",
                    "request": "launch",
                    "module": "uvicorn",
                    "args": [c["import_name"] + ".api:app"],
                    "cwd": cwd,
                    "python": cwd + "/.venv/bin/python",
                }
            )
        elif (
            c["profile"] != "existing"
            and c["language"] in ("javascript", "typescript")
            and "dev" in c["commands"]
        ):
            launches.append(
                {
                    "name": c["id"],
                    "type": "node-terminal",
                    "request": "launch",
                    "command": shlex.join(c["commands"]["dev"]["argv"]),
                    "cwd": cwd,
                }
            )
    settings = {}
    if "charliermarsh.ruff" in ids:
        settings["[python]"] = {"editor.defaultFormatter": "charliermarsh.ruff"}
    if "esbenp.prettier-vscode" in ids:
        for lang in ("javascript", "javascriptreact", "typescript", "typescriptreact"):
            settings["[" + lang + "]"] = {"editor.defaultFormatter": "esbenp.prettier-vscode"}

    def python_settings(c, base):
        result = {}
        if c["package_manager"] in ("uv", "pip"):
            result["python.defaultInterpreterPath"] = base + "/.venv/bin/python"
        if "pytest" in str(c["commands"]):
            result.update(
                {
                    "python.testing.pytestEnabled": True,
                    "python.testing.unittestEnabled": False,
                    "python.testing.cwd": base,
                }
            )
        return result

    if len(m["components"]) == 1 and m["components"][0]["language"] == "python":
        c = m["components"][0]
        settings.update(python_settings(c, base + ("" if c["path"] == "." else "/" + c["path"])))
    j(".vscode/extensions.json", {"recommendations": ids}, "json")
    j(".vscode/settings.json", settings, "json")
    j(".vscode/tasks.json", {"version": "2.0.0", "tasks": tasks}, "json")
    if launches:
        j(".vscode/launch.json", {"version": "0.2.0", "configurations": launches}, "json")
    if multi:
        j(
            m["project"]["name"] + ".code-workspace",
            {
                "folders": [{"name": "repository", "path": "."}]
                + [{"name": c["id"], "path": c["path"]} for c in m["components"]],
                "settings": {},
            },
        )
        for c in m["components"]:
            if c["language"] == "python":
                j(
                    c["path"] + "/.vscode/settings.json",
                    python_settings(c, "${workspaceFolder}"),
                    "json",
                )


def container_setup(m):
    steps = []
    managers = {c["package_manager"] for c in m["components"]}
    if "uv" in managers:
        steps.append("python -m pip install --user uv==0.9.5")
    if "poetry" in managers:
        steps.append("python -m pip install --user poetry==2.2.1")
    for manager in ("pnpm", "yarn", "bun"):
        versions = {
            c["manager_version"] for c in m["components"] if c["package_manager"] == manager
        }
        if versions:
            if len(versions) != 1 or not next(iter(versions)):
                raise BootstrapError("Container requires a single explicit " + manager + " version")
            steps.append(
                "npm install --global " + shlex.quote(manager + "@" + next(iter(versions)))
            )
    for c in m["components"]:
        commands = [c["commands"][k] for k in ("prepare", "ci_install") if k in c["commands"]]
        if commands:
            steps.append(
                "(cd "
                + shlex.quote(c["path"])
                + " && "
                + " && ".join(shlex.join(x["argv"]) for x in commands)
                + ")"
            )
    return " && ".join(steps) or "true"
