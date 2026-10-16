"""Behavioral regression tests; use disposable roots, never live provider mutation."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bootstrap_core.engine import execute, finish_state, make_plan, recover
from bootstrap_core.integrations import ci_config, commit_files, remote_apply
from bootstrap_core.model import CATALOG, normalize
from bootstrap_core.render import ENV, render
from bootstrap_core.util import BootstrapError, dumps, read_json, sha
from scan_project import inventory


def manifest(profile="python.cli", language="python", manager="uv"):
    return {
        "schema_version": 1,
        "project": {
            "name": "sample-project",
            "description": "A behavior-test scaffold.",
            "mode": "init",
        },
        "components": [
            {
                "id": "app",
                "path": ".",
                "language": language,
                "profile": profile,
                "package_manager": manager,
            }
        ],
        "git": {"initialize": False, "commit": "never"},
    }


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_all_variants_render_and_rerun_without_diff(self):
        for profile, spec in CATALOG["profiles"].items():
            if profile == "existing":
                continue
            for language in spec["languages"]:
                with (
                    self.subTest(profile=profile, language=language),
                    tempfile.TemporaryDirectory() as d,
                ):
                    raw = manifest(profile, language, "uv" if language == "python" else "pnpm")
                    plan = make_plan(Path(d), raw)
                    self.assertFalse(plan["conflicts"])
                    self.assertEqual(execute(plan, files_only=True)["status"], "partial")
                    again = make_plan(Path(d), raw)
                    self.assertEqual(again["operations"], [])
                    self.assertFalse(again["conflicts"])

    def test_readme_source_provenance_survives_managed_append(self):
        self.put("README.md", "# Existing brief\nKeep these original requirements.\n")
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "README.md"
                source.write_text("# Original brief without final newline")
                original = sha(source.read_bytes())
                raw = manifest()
                raw["sources"] = [{"path": "README.md", "kind": "readme"}]
                if explicit:
                    raw["sources"][0]["sha256"] = original
                plan = make_plan(root, raw)
                execute(plan, files_only=True)
                persisted = read_json(root / ".bootstrap/project.json")
                model = normalize(persisted, root)
                self.assertEqual(model["sources"][0]["sha256"], original)
                self.assertEqual(make_plan(root, raw)["operations"], [])
                self.assertEqual(execute(plan, files_only=True, resume=True)["status"], "partial")
                source.write_text("Changed requirements\n" + source.read_text())
                with self.assertRaises(BootstrapError):
                    normalize(persisted, root)

    def test_full_existing_run_and_verify_without_registry(self):
        self.put(
            "package.json",
            '{"name":"existing-app","type":"module","scripts":{"test":"node --test"}}',
        )
        self.put(
            "check.test.js",
            "import test from 'node:test';import assert from 'node:assert/strict';test('behavior',()=>assert.equal(2+3,5));",
        )
        self.put("README.md", "# Project requirements\nKeep them.\n")
        raw = manifest("existing", "javascript", "npm")
        raw["project"]["mode"] = "adopt"
        raw["ci"] = {"provider": "none"}
        raw["sources"] = [{"path": "README.md", "kind": "readme"}]
        raw["components"][0]["commands"] = {
            "install": {
                "argv": [
                    "node",
                    "-e",
                    "JSON.parse(require('node:fs').readFileSync('package.json'))",
                ]
            }
        }
        plan = make_plan(self.root, raw)
        result = execute(plan)
        self.assertEqual(result["status"], "complete", result)
        persisted = read_json(self.root / ".bootstrap/project.json")
        from bootstrap_core.engine import run_checks

        self.assertTrue(run_checks(normalize(persisted, self.root), self.root))
        self.assertEqual(make_plan(self.root, raw)["operations"], [])

    def test_generated_formatter_does_not_sweep_user_files(self):
        self.put("src/user_notes.py", "x= 1\n")
        raw = manifest()
        plan = make_plan(self.root, raw)
        execute(plan, files_only=True)
        from bootstrap_core.engine import format_generated

        cmd = format_generated(plan["model"]["components"][0], plan, self.root)
        self.assertNotIn("src/user_notes.py", cmd["argv"])
        self.assertIn("src/sample_project/cli.py", cmd["argv"])

    def test_obsolete_plan_fails_before_apply(self):
        plan = make_plan(self.root, manifest())
        plan.pop("managed_outputs")
        with self.assertRaisesRegex(BootstrapError, "obsolete plan"):
            execute(plan, files_only=True)
        self.assertFalse((self.root / "README.md").exists())

    def test_plan_is_read_only(self):
        self.put("PRD.md", "Build a CLI")
        make_plan(self.root, manifest())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["PRD.md"])

    def test_preserves_authored_text_and_additive_editor_settings(self):
        self.put("README.md", "# Existing notes\nDo not discard these.\n")
        self.put(".vscode/settings.json", '{"editor.tabSize": 4}\n')
        raw = manifest()
        plan = make_plan(self.root, raw)
        execute(plan, files_only=True)
        self.assertIn("Do not discard these.", (self.root / "README.md").read_text())
        self.assertEqual(read_json(self.root / ".vscode/settings.json")["editor.tabSize"], 4)
        self.assertFalse(make_plan(self.root, raw)["conflicts"])

    def test_user_edited_owned_file_is_conflict(self):
        raw = manifest()
        execute(make_plan(self.root, raw), files_only=True)
        self.put("src/sample_project/cli.py", "# user customization\n")
        plan = make_plan(self.root, raw)
        self.assertIn("src/sample_project/cli.py", [x["path"] for x in plan["conflicts"]])
        with self.assertRaises(BootstrapError):
            execute(plan, files_only=True)
        self.assertEqual(
            (self.root / "src/sample_project/cli.py").read_text(), "# user customization\n"
        )

    def test_managed_block_does_not_overwrite_user_edit(self):
        raw = manifest()
        execute(make_plan(self.root, raw), files_only=True)
        p = self.root / "AGENTS.md"
        p.write_text(p.read_text().replace("Working agreements", "User agreements"))
        self.assertTrue(make_plan(self.root, raw)["conflicts"])

    def test_jsonc_is_preserved_and_reported(self):
        before = '{\n// user comment\n"editor.tabSize":4\n}\n'
        self.put(".vscode/settings.json", before)
        plan = make_plan(self.root, manifest())
        self.assertIn(".vscode/settings.json", [x["path"] for x in plan["conflicts"]])
        self.assertEqual((self.root / ".vscode/settings.json").read_text(), before)

    def test_stale_input_stops_before_writes(self):
        p = self.put("PRD.md", "version one")
        plan = make_plan(self.root, manifest())
        p.write_text("version two")
        with self.assertRaises(BootstrapError):
            execute(plan, files_only=True)
        self.assertFalse((self.root / "README.md").exists())

    def test_path_escape_and_symlink_are_rejected(self):
        for path in ("../escape", "/tmp/escape", ".git/hooks", "a/../../b", "C:\\escape"):
            with self.subTest(path=path):
                raw = manifest()
                raw["components"][0]["path"] = path
                with self.assertRaises(BootstrapError):
                    make_plan(self.root, raw)
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "src").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(BootstrapError):
                make_plan(self.root, manifest())

    def test_scanner_excludes_secrets_cache_and_preserves_editor(self):
        self.put(".env", "TOKEN=secret")
        self.put("node_modules/secret.js", "bad")
        self.put(".vscode/settings.json", "{}")
        self.put("main.py", "import requests\n")
        self.put("tests/test_main.py", "import pytest\n")
        data = inventory(self.root)
        names = {x["path"] for x in data["files"]}
        self.assertNotIn(".env", names)
        self.assertNotIn("node_modules/secret.js", names)
        self.assertIn(".vscode/settings.json", names)
        self.assertNotIn("TOKEN=secret", json.dumps(data))
        raw = manifest()
        raw["sources"] = [{"path": ".env", "kind": "other"}]
        with self.assertRaises(BootstrapError):
            make_plan(self.root, raw)

    def test_unknown_jinja_variable_fails(self):
        from jinja2 import UndefinedError

        with self.assertRaises(UndefinedError):
            ENV.from_string("{{ missing.value }}").render()

    def test_schema_and_dependency_cycles(self):
        raw = manifest()
        raw["unexpected"] = True
        with self.assertRaises(BootstrapError):
            normalize(raw, self.root)
        raw = manifest()
        raw["components"][0]["depends_on"] = ["app"]
        with self.assertRaises(BootstrapError):
            normalize(raw, self.root)

    def test_deviation_required_and_reserved_paths(self):
        raw = manifest()
        raw["overlays"] = [{"path": "hello.txt", "content": "hello", "deviation": "missing"}]
        with self.assertRaises(BootstrapError):
            make_plan(self.root, raw)
        raw["deviations"] = [
            {"id": "missing", "requirement": "custom", "reason": "needed", "validation": "read"}
        ]
        raw["overlays"][0]["path"] = ".bootstrap/managed-files.json"
        with self.assertRaises(BootstrapError):
            make_plan(self.root, raw)

    def test_move_recovers_without_losing_content(self):
        self.put("old.txt", "existing material\n")
        raw = manifest()
        raw["project"]["mode"] = "reorganize"
        raw["moves"] = [
            {"source": "old.txt", "destination": "docs/old.txt", "reason": "Requested organization"}
        ]
        plan = make_plan(self.root, raw)
        self.assertEqual(execute(plan, files_only=True)["status"], "partial")
        self.assertFalse((self.root / "old.txt").exists())
        result = recover(self.root)
        self.assertEqual(result["status"], "complete")
        self.assertEqual((self.root / "old.txt").read_text(), "existing material\n")
        self.assertFalse((self.root / "docs/old.txt").exists())

    def test_recovery_preserves_later_user_change(self):
        execute(make_plan(self.root, manifest()), files_only=True)
        self.put("README.md", "my new text")
        result = recover(self.root)
        self.assertEqual(result["status"], "partial")
        self.assertIn("README.md", result["conflicts"])
        self.assertEqual((self.root / "README.md").read_text(), "my new text")

    def test_resume_reconciles_interrupted_atomic_write(self):
        plan = make_plan(self.root, manifest())
        execute(plan, files_only=True)
        path = self.root / ".bootstrap/local/run.json"
        journal = read_json(path)
        journal["pending"] = journal["applied"].pop()
        path.write_text(dumps(journal))
        self.assertEqual(execute(plan, files_only=True, resume=True)["status"], "partial")
        self.assertNotIn("pending", read_json(path))

    def test_formatter_normalized_file_is_stable(self):
        raw = manifest()
        plan = make_plan(self.root, raw)
        execute(plan, files_only=True)
        p = self.root / "src/sample_project/cli.py"
        p.write_text(p.read_text() + "\n")
        journal = read_json(self.root / ".bootstrap/local/run.json")
        finish_state(self.root, plan, journal)
        self.assertEqual(make_plan(self.root, raw)["operations"], [])

    def test_failed_install_does_not_commit_or_contact_remote(self):
        raw = manifest()
        raw["components"][0]["commands"] = {
            "install": {"argv": [sys.executable, "-c", "raise SystemExit(7)"]}
        }
        with (
            patch("bootstrap_core.engine.commit_files") as commit,
            patch("bootstrap_core.engine.remote_apply") as remote,
        ):
            result = execute(make_plan(self.root, raw))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["commands"][-1]["returncode"], 7)
        commit.assert_not_called()
        remote.assert_not_called()

    def test_disabled_remote_does_not_call_provider(self):
        with patch("bootstrap_core.integrations.run_command") as run:
            self.assertEqual(
                remote_apply(self.root, {"mode": "none"}, False)["status"], "not_requested"
            )
        run.assert_not_called()

    def test_remote_requires_session_authorization(self):
        with patch("bootstrap_core.integrations.run_command") as run:
            with self.assertRaises(BootstrapError):
                remote_apply(
                    self.root, {"mode": "link", "url": "https://github.com/example/repo.git"}, False
                )
        run.assert_not_called()

    def test_existing_manager_and_no_automatic_uv_migration(self):
        self.put(
            "pyproject.toml",
            '[tool.poetry]\nname="old"\n[tool.poetry.group.dev.dependencies]\npytest="*"\n',
        )
        self.put("poetry.lock", "# existing lock")
        raw = manifest("existing", "python", "poetry")
        raw["project"]["mode"] = "adopt"
        plan = make_plan(self.root, raw)
        self.assertNotIn("pyproject.toml", [x["path"] for x in plan["operations"]])
        pipeline = next(
            x["content"] for x in plan["operations"] if x["path"].endswith("bootstrap-ci.yml")
        )
        self.assertIn("poetry install", pipeline)
        self.assertNotIn("uv sync", pipeline)
        raw["components"][0]["package_manager"] = "uv"
        with self.assertRaises(BootstrapError):
            make_plan(self.root, raw)

    def test_multicomponent_commands_and_workspace(self):
        raw = manifest("node.library", "typescript", "pnpm")
        a = raw["components"][0]
        a["id"] = "lib"
        a["path"] = "packages/lib"
        b = copy.deepcopy(a)
        b.update(id="app", path="apps/app", depends_on=["lib"])
        raw["components"].append(b)
        raw["editor"] = {"layout": "multi_root"}
        model = normalize(raw, self.root)
        outputs = render(model, raw)
        self.assertIn("pnpm-workspace.yaml", outputs)
        tasks = json.loads(outputs[".vscode/tasks.json"]["content"])["tasks"]
        self.assertEqual(tasks[0]["options"]["cwd"], "${workspaceFolder:repository}/packages/lib")
        _, ci = ci_config(model)
        self.assertEqual(list(ci["jobs"]), ["workspace"])
        steps = ci["jobs"]["workspace"]["steps"]
        names = [s.get("name") for s in steps]
        self.assertLess(names.index("lib:build"), names.index("app:ci_install"))

    def test_python_editor_and_harness_paths(self):
        raw = manifest()
        outputs = render(normalize(raw, self.root), raw)
        settings = json.loads(outputs[".vscode/settings.json"]["content"])
        self.assertEqual(
            settings["python.defaultInterpreterPath"], "${workspaceFolder}/.venv/bin/python"
        )
        self.assertIn("@AGENTS.md", outputs["CLAUDE.md"]["content"])
        self.assertIn(".agents/skills/verify-project/SKILL.md", outputs)
        self.assertIn(".claude/skills/verify-project/SKILL.md", outputs)
        self.assertIn(".codex/config.toml", outputs)
        self.assertFalse(any(p.startswith(".antigravity") for p in outputs))

    def test_devcontainer_is_opt_in_and_installs_manager(self):
        raw = manifest()
        m = normalize(raw, self.root)
        self.assertFalse(any(p.startswith(".devcontainer") for p in render(m, raw)))
        raw["infrastructure"] = {"enabled": True, "devcontainer": True}
        content = render(normalize(raw, self.root), raw)[".devcontainer/devcontainer.json"][
            "content"
        ]
        self.assertIn("uv==", content)
        self.assertIn("uv sync --locked", content)
        raw["infrastructure"]["provider"] = "unimplemented"
        with self.assertRaises(BootstrapError):
            normalize(raw, self.root)

    def test_native_js_library_behavior_runs(self):
        raw = manifest("node.library", "javascript", "npm")
        execute(make_plan(self.root, raw), files_only=True)
        p = subprocess.run(["node", "--test"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_native_python_cli_behavior_runs(self):
        raw = manifest()
        execute(make_plan(self.root, raw), files_only=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root / "src")
        p = subprocess.run(
            [sys.executable, "-m", "sample_project.cli", "--name", "Ada"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "Hello, Ada!")

    def test_staged_changes_survive_commit_deferral(self):
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=self.root, check=True, capture_output=True
        )
        self.put("unrelated.txt", "preserve index")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=self.root, check=True)
        before = (self.root / ".git/index").read_bytes()
        with self.assertRaises(BootstrapError):
            commit_files(
                self.root,
                ["new.txt"],
                {"commit": "after_verification", "additional_paths": []},
                False,
            )
        self.assertEqual((self.root / ".git/index").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
