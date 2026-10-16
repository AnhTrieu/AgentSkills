#!/usr/bin/env python3
"""Run real install/check pipelines in disposable roots; requires registry access."""

import argparse
import json
from pathlib import Path
import tempfile
from bootstrap_core.engine import execute, make_plan
from bootstrap_core.model import CATALOG


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="all")
    parser.add_argument("--language", choices=["python", "javascript", "typescript"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = []
    for profile, spec in CATALOG["profiles"].items():
        if profile == "existing" or args.profile not in ("all", profile):
            continue
        for language in spec["languages"]:
            if args.language and args.language != language:
                continue
            with tempfile.TemporaryDirectory(prefix="bootstrap-profile-") as d:
                raw = {
                    "schema_version": 1,
                    "project": {
                        "name": "profile-example",
                        "description": "Disposable integration check.",
                        "mode": "init",
                    },
                    "components": [
                        {
                            "id": "app",
                            "path": ".",
                            "language": language,
                            "profile": profile,
                            "package_manager": "uv" if language == "python" else "pnpm",
                        }
                    ],
                    "git": {"initialize": False, "commit": "never"},
                    "ci": {"provider": "github"},
                }
                result = execute(make_plan(Path(d), raw))
                if result["status"] == "complete":
                    rerun = make_plan(Path(d), raw)
                    result["rerun_operations"] = len(rerun["operations"])
                    result["rerun_conflicts"] = rerun["conflicts"]
                    if rerun["operations"] or rerun["conflicts"]:
                        result["status"] = "failed"
                reports.append({"profile": profile, "language": language, **result})
                if result["status"] != "complete":
                    print(json.dumps(result, indent=2), flush=True)
                print(
                    json.dumps(
                        {
                            "profile": profile,
                            "language": language,
                            "status": result["status"],
                            "error": result.get("error"),
                        }
                    ),
                    flush=True,
                )
    if not reports:
        parser.error("No matching profile variants")
    if args.output:
        args.output.write_text(json.dumps(reports, indent=2) + "\n")
    return 0 if all(r["status"] == "complete" for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
