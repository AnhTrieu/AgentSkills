#!/usr/bin/env python3
"""Use --help for the manifest-driven bootstrap CLI."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser(
        description="Template-first project bootstrap; PRD/SDD interpretation is performed by the calling agent."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("root", type=Path)
    sub.add_parser("catalog")
    for name in ["validate", "plan"]:
        p = sub.add_parser(name)
        p.add_argument("--root", required=True, type=Path)
        p.add_argument("--config", required=True, type=Path)
        if name == "plan":
            p.add_argument("--output", type=Path)
    for name in ["apply", "resume"]:
        p = sub.add_parser(name)
        p.add_argument("--plan", required=True, type=Path)
        p.add_argument("--files-only", action="store_true")
        p.add_argument("--allow-remote", action="store_true")
    for name in ["verify", "recover"]:
        p = sub.add_parser(name)
        p.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.cmd == "scan":
        from scan_project import inventory

        try:
            print(json.dumps(inventory(args.root), indent=2))
            return 0
        except (OSError, ValueError) as e:
            print(json.dumps({"status": "failed", "error": str(e)}))
            return 1
    try:
        from bootstrap_core.util import BootstrapError, CommandError, dumps, read_json
        from bootstrap_core.model import normalize, CATALOG
        from bootstrap_core.engine import make_plan, execute, recover, run_checks

        if args.cmd == "catalog":
            result = CATALOG
        elif args.cmd == "validate":
            normalize(read_json(args.config), args.root)
            result = {"status": "valid"}
        elif args.cmd == "plan":
            result = make_plan(args.root, read_json(args.config))
            if args.output:
                if args.output.resolve().is_relative_to(args.root.resolve()):
                    raise BootstrapError(
                        "Write the plan outside the target so planning remains read-only"
                    )
                args.output.write_text(dumps(result))
                result = {
                    "status": "conflicts" if result["conflicts"] else "planned",
                    "plan": str(args.output),
                    "operations": len(result["operations"]),
                    "conflicts": result["conflicts"],
                }
        elif args.cmd in ("apply", "resume"):
            result = execute(
                read_json(args.plan),
                files_only=args.files_only,
                allow_remote=args.allow_remote,
                resume=args.cmd == "resume",
            )
        elif args.cmd == "recover":
            result = recover(args.root)
        else:
            m = normalize(read_json(args.root / ".bootstrap/project.json"), args.root)
            result = {"status": "complete", "checks": run_checks(m, args.root)}
        print(dumps(result), end="")
        return 1 if result.get("status") in ("failed", "conflicts") else 0
    except ImportError as e:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": "Missing helper dependency: " + str(e),
                    "remedy": "Run through the skill uv project; see SKILL.md",
                }
            )
        )
        return 2
    except (BootstrapError, OSError, ValueError) as e:
        result = {"status": "failed", "error": str(e)}
        if isinstance(e, CommandError):
            result["command"] = e.result
        print(dumps(result), end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
