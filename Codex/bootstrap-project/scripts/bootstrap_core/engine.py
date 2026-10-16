from __future__ import annotations
from copy import deepcopy
import difflib
import json
import jsonschema
from pathlib import Path
import uuid
import fcntl
from contextlib import contextmanager
from .model import normalize, SKILL, CATALOG, CHECKS
from .render import render, extension_ids
from .integrations import init_git, commit_files, remote_apply
from .util import (
    BootstrapError,
    CommandError,
    atomic_write,
    command,
    dumps,
    file_hash,
    read_json,
    relative,
    run_command,
    sha,
    within,
)
from scan_project import inventory, is_secret

MANAGED = ".bootstrap/managed-files.json"


def markers(path):
    return (
        ("# bootstrap:start " + path, "# bootstrap:end " + path)
        if path == ".gitignore"
        else ("<!-- bootstrap:start " + path + " -->", "<!-- bootstrap:end " + path + " -->")
    )


def block_value(text, path):
    a, b = markers(path)
    if text.count(a) != 1 or text.count(b) != 1:
        return None
    start = text.index(a)
    end = text.index(b) + len(b)
    if end < start:
        raise BootstrapError("Invalid managed markers: " + path)
    return text[start:end]


def merge_json(a, b, path=""):
    result = deepcopy(a)
    for k, v in b.items():
        if k not in result:
            result[k] = v
        elif isinstance(v, dict) and isinstance(result[k], dict):
            result[k] = merge_json(result[k], v, path + "." + k)
        elif isinstance(v, list) and isinstance(result[k], list):
            for x in v:
                ident = next(
                    (x[z] for z in ["label", "name"] if isinstance(x, dict) and z in x), None
                )
                matches = [
                    old
                    for old in result[k]
                    if isinstance(old, dict)
                    and ident is not None
                    and ident in [old.get("label"), old.get("name")]
                ]
                if matches and matches[0] != x:
                    raise BootstrapError(
                        "JSON entry conflict: " + path + "." + k + ":" + str(ident)
                    )
                if x not in result[k]:
                    result[k].append(x)
        elif result[k] != v:
            raise BootstrapError("JSON key conflict: " + path + "." + k)
    return result


def compose(path, wanted, current, old):
    policy = wanted["policy"]
    body = wanted["content"]
    if policy in ("block", "ignore"):
        a, b = markers(path)
        new = a + "\n" + body.rstrip() + "\n" + b
        previous = block_value(current or "", path)
        if previous:
            if previous != new and (not old or sha(previous) != old.get("owned_hash")):
                raise BootstrapError("User edited managed section: " + path)
            content = current.replace(previous, new, 1)
        elif old:
            raise BootstrapError("Managed section was removed: " + path)
        else:
            content = (current.rstrip() + "\n\n" if current else "") + new + "\n"
        return content, sha(new)
    if (
        old
        and old.get("template_hash") == sha(body)
        and current is not None
        and sha(current) == old.get("file_hash")
    ):
        return current, old.get("owned_hash")
    if current is None or current == body or (old and sha(current) == old.get("file_hash")):
        return body, sha(body)
    if policy == "preserve":
        return current, None
    if policy == "json" and not old:
        try:
            return dumps(merge_json(json.loads(current), json.loads(body))), None
        except json.JSONDecodeError as e:
            raise BootstrapError(
                "JSONC/custom configuration requires a reviewed merge; preserve comments: " + path
            ) from e
    raise BootstrapError("Existing or edited file conflict: " + path)


def bundle_digest():
    files = sorted(
        [
            *(SKILL / "assets").rglob("*"),
            *(SKILL / "scripts").rglob("*.py"),
            SKILL / "pyproject.toml",
        ]
    )
    return sha(
        "".join(p.relative_to(SKILL).as_posix() + sha(p.read_bytes()) for p in files if p.is_file())
    )


def make_plan(root, raw):
    root = Path(root).resolve()
    raw = deepcopy(raw)
    m = normalize(raw, root)
    if m["sources"]:
        raw["sources"] = deepcopy(m["sources"])
    scan = inventory(root)
    if scan["git"]["root"] and not scan["git"]["is_root"]:
        raise BootstrapError("Use the Git root, not a nested directory")
    outputs = render(m, raw)
    state = read_json(within(root, MANAGED), {"files": {}})
    template_digest = bundle_digest()
    outputs[".bootstrap/template-lock.json"] = {
        "content": dumps(
            {
                "skill_version": CATALOG["release"],
                "template_digest": template_digest,
                "profiles": {
                    c["profile"]: CATALOG["profiles"][c["profile"]]["version"]
                    for c in m["components"]
                },
            }
        ),
        "policy": "file",
        "owner": "core",
    }
    moves = []
    moved_sources = set()
    moved_content = {}
    for move in m["moves"]:
        src = relative(move["source"])
        dst = relative(move["destination"])
        if is_secret(src) or is_secret(dst):
            raise BootstrapError("Private files cannot be relocated by bootstrap")
        if src in moved_sources or dst in moved_content:
            raise BootstrapError("Duplicate move path")
        p = within(root, src)
        q = within(root, dst)
        if not p.is_file() or q.exists():
            raise BootstrapError("Move requires existing source and absent destination: " + src)
        moved_content[dst] = p.read_text()
        moved_sources.add(src)
        moves.append(move)
        if dst in outputs and outputs[dst]["content"] != moved_content[dst]:
            raise BootstrapError(
                "Move destination also generated; split relocation and template adoption: " + dst
            )
        outputs.setdefault(dst, {"content": moved_content[dst], "policy": "file", "owner": "move"})
    if moved_sources & set(outputs):
        raise BootstrapError("Move source would be regenerated")
    ops = []
    conflicts = []
    records = deepcopy(state["files"])
    seen = set()
    for path, wanted in sorted(outputs.items()):
        if path.casefold() in seen:
            raise BootstrapError("Case-colliding output path: " + path)
        seen.add(path.casefold())
        if is_secret(path):
            raise BootstrapError("Secret-like output rejected: " + path)
        if path.startswith(".bootstrap/local/"):
            raise BootstrapError("Outputs cannot overwrite execution state")
        p = within(root, path)
        before = file_hash(p)
        current = p.read_text() if p.exists() else None
        try:
            content, owned = compose(path, wanted, current, records.get(path))
        except BootstrapError as e:
            conflicts.append({"path": path, "reason": str(e), "proposed": wanted["content"]})
            continue
        if before != sha(content):
            ops.append(
                {
                    "path": path,
                    "before": before,
                    "after": sha(content),
                    "content": content,
                    "diff": "".join(
                        difflib.unified_diff(
                            (current or "").splitlines(True),
                            content.splitlines(True),
                            fromfile=path,
                            tofile=path,
                        )
                    ),
                }
            )
        # Preserve user-owned JSON and preserved files without claiming ownership of their content.
        if owned is not None:
            records[path] = {
                "file_hash": sha(content),
                "owned_hash": owned,
                "policy": wanted["policy"],
                "owner": wanted["owner"],
                "template_hash": sha(wanted["content"]),
            }
    for source in m["sources"]:
        if source["path"] in records:
            records[source["path"]]["source_sha256"] = source["sha256"]
    for src in sorted(moved_sources):
        p = within(root, src)
        ops.append(
            {
                "path": src,
                "before": file_hash(p),
                "after": None,
                "content": None,
                "diff": "remove moved source " + src,
            }
        )
        records.pop(src, None)
    meta = dumps({"schema_version": 1, "files": records})
    p = within(root, MANAGED)
    if file_hash(p) != sha(meta):
        ops.append(
            {
                "path": MANAGED,
                "before": file_hash(p),
                "after": sha(meta),
                "content": meta,
                "diff": "Update managed-file ownership records",
            }
        )
    plan = {
        "schema_version": 1,
        "root": str(root),
        "manifest": raw,
        "model": m,
        "operations": ops,
        "conflicts": conflicts,
        "inputs": {f["path"]: f["sha256"] for f in scan["files"]},
        "git_before": scan["git"],
        "commands": {c["id"]: c["commands"] for c in m["components"]},
        "template_digest": template_digest,
        "managed_outputs": sorted(outputs),
    }
    plan["digest"] = sha(dumps(plan))
    return plan


def check_plan(plan):
    try:
        jsonschema.validate(plan, read_json(SKILL / "assets/schemas/plan.schema.json"))
    except jsonschema.ValidationError as e:
        raise BootstrapError("Invalid or obsolete plan; regenerate it: " + e.message) from e
    if plan["template_digest"] != bundle_digest():
        raise BootstrapError("Skill bundle changed; regenerate the plan")
    p = deepcopy(plan)
    digest = p.pop("digest", None)
    if digest != sha(dumps(p)):
        raise BootstrapError("Plan digest mismatch; regenerate the plan")
    if p.get("schema_version") != 1:
        raise BootstrapError("Unsupported plan schema")
    root = Path(plan["root"]).resolve()
    # Validate the source manifest, not arbitrary injected model commands.
    expected = normalize(plan["manifest"], root)
    if expected != plan["model"]:
        raise BootstrapError("Plan model differs from validated manifest")
    for op in plan["operations"]:
        if op["path"].startswith(".bootstrap/local/"):
            raise BootstrapError("Operation targets private execution state")
        within(root, op["path"])
        if is_secret(op["path"]):
            raise BootstrapError("Secret output rejected")
        if op["content"] is not None and sha(op["content"]) != op["after"]:
            raise BootstrapError("Operation digest mismatch")
    return root


@contextmanager
def execution_lock(root):
    p = within(root, ".bootstrap/local/execution.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise BootstrapError("Another bootstrap operation is active") from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_checks(m, root):
    results = []
    for c in m["components"]:
        for k in CHECKS:
            if k in c["commands"]:
                results.append(run_command(c["commands"][k], root))
    return results


def finish_state(root, plan, journal):
    p = within(root, MANAGED)
    state = read_json(p)
    # Only accept command-induced changes to known generated files. Authored/unmanaged files stay unowned.
    for name, rec in state["files"].items():
        if name not in plan["managed_outputs"]:
            continue
        q = within(root, name)
        if q.is_file():
            rec["file_hash"] = file_hash(q)
            if rec["policy"] not in ("block", "ignore"):
                rec["owned_hash"] = rec["file_hash"]
    atomic_write(p, dumps(state))
    for op in journal["applied"]:
        if within(root, op["path"]).exists():
            op["after"] = file_hash(within(root, op["path"]))


def format_generated(c, plan, root):
    """Format only generated source; never sweep unrelated user files in source directories."""
    raw_c = next(x for x in plan["manifest"]["components"] if x["id"] == c["id"])
    if "format_fix" in raw_c.get("commands", {}):
        return c["commands"]["format_fix"]
    prefix = "" if c["path"] == "." else c["path"] + "/"
    records = read_json(within(root, MANAGED))["files"]
    paths = []
    for path, rec in records.items():
        if path not in plan["managed_outputs"] or rec["owner"] != c["id"]:
            continue
        local = path[len(prefix) :]
        if not local.startswith(("src/", "tests/", "app/")):
            continue
        if local.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".mjs")):
            paths.append(local)
    if not paths:
        return None
    if c["language"] == "python":
        argv = ["uv", "run", "--no-sync", "ruff", "format", *sorted(paths)]
    elif c["package_manager"] == "pnpm":
        argv = ["pnpm", "exec", "prettier", "--write", *sorted(paths)]
    else:
        argv = ["npm", "exec", "--", "prettier", "--write", *sorted(paths)]
    return command(c["id"] + ":format_fix", argv, c["path"])


def execute(plan, *, files_only=False, allow_remote=False, resume=False):
    root = check_plan(plan)
    m = plan["model"]
    if plan["conflicts"]:
        raise BootstrapError("Resolve plan conflicts before applying")
    jp = within(root, ".bootstrap/local/run.json")
    with execution_lock(root):
        journal = read_json(jp) if resume else None
        if resume and (not journal or journal["plan_digest"] != plan["digest"]):
            raise BootstrapError("No matching resumable run")
        if resume and journal.get("recovery"):
            raise BootstrapError("Recovered run requires a new plan")
        if not resume:
            for name, h in plan["inputs"].items():
                if file_hash(within(root, name)) != h:
                    raise BootstrapError("Input changed after planning: " + name)
            for op in plan["operations"]:
                if file_hash(within(root, op["path"])) != op["before"]:
                    raise BootstrapError("Output changed after planning: " + op["path"])
            journal = {
                "run_id": uuid.uuid4().hex,
                "plan_digest": plan["digest"],
                "status": "in_progress",
                "applied": [],
                "commands": [],
                "stages": {},
            }
            atomic_write(jp, dumps(journal))
        report = journal
        try:
            pending = journal.get("pending")
            if pending:
                current = file_hash(within(root, pending["path"]))
                if current == pending["after"]:
                    journal["applied"].append(pending)
                elif current != pending["before"]:
                    raise BootstrapError("Interrupted file has changed: " + pending["path"])
                journal.pop("pending", None)
                atomic_write(jp, dumps(journal))
            done = {op["path"]: op for op in journal["applied"]}
            for op in plan["operations"]:
                p = within(root, op["path"])
                if op["path"] in done:
                    if file_hash(p) != done[op["path"]]["after"]:
                        raise BootstrapError("File changed since interrupted run: " + op["path"])
                    continue
                if file_hash(p) != op["before"]:
                    raise BootstrapError("Concurrent change: " + op["path"])
                saved = {k: op[k] for k in ("path", "before", "after")}
                saved["previous"] = p.read_text() if p.exists() else None
                # Persist intent before mutation so an interrupted write is recoverable.
                journal["pending"] = saved
                atomic_write(jp, dumps(journal))
                if op["content"] is None:
                    p.unlink()
                else:
                    atomic_write(p, op["content"])
                journal["applied"].append(saved)
                journal.pop("pending", None)
                atomic_write(jp, dumps(journal))
            report["stages"]["files"] = {"status": "succeeded"}
            if files_only:
                report["status"] = "partial"
                report["stages"]["installation"] = {"status": "not_requested"}
            else:
                info = report["stages"].get("git") or init_git(root, m["git"])
                report["stages"]["git"] = info
                atomic_write(jp, dumps(journal))
                for c in m["components"]:
                    for k in ("prepare", "install", "format_fix"):
                        if k not in c["commands"] or (
                            k == "format_fix"
                            and (m["project"]["mode"] != "init" or c["profile"] == "existing")
                        ):
                            continue
                        # Rerun installs on resume; managers reconcile the actual environment.
                        cmd = (
                            format_generated(c, plan, root)
                            if k == "format_fix"
                            else c["commands"][k]
                        )
                        if cmd:
                            report["commands"].append(run_command(cmd, root))
                        atomic_write(jp, dumps(journal))
                    report["commands"].extend(run_checks({"components": [c]}, root))
                report["stages"]["installation"] = {"status": "succeeded"}
                report["stages"]["verification"] = {"status": "succeeded"}
                if m["editor"]["enabled"] and m["editor"]["extension_installation"] == "install":
                    if not m["editor"].get("profile"):
                        raise BootstrapError(
                            "Extension installation requires a selected VS Code profile"
                        )
                    for ext in extension_ids(m):
                        report["commands"].append(
                            run_command(
                                command(
                                    "vscode:" + ext,
                                    [
                                        "code",
                                        "--profile",
                                        m["editor"]["profile"],
                                        "--install-extension",
                                        ext,
                                    ],
                                ),
                                root,
                            )
                        )
                finish_state(root, plan, journal)
                paths = [op["path"] for op in plan["operations"]] + [MANAGED]
                for c in m["components"]:
                    prefix = "" if c["path"] == "." else c["path"] + "/"
                    paths += [
                        prefix + x
                        for x in [
                            "uv.lock",
                            "pnpm-lock.yaml",
                            "package-lock.json",
                            "poetry.lock",
                            "yarn.lock",
                            "bun.lock",
                        ]
                    ]
                paths.append("pnpm-lock.yaml")
                report["stages"]["commit"] = commit_files(root, paths, m["git"], info["created"])
                report["stages"]["remote"] = remote_apply(root, m["remote"], allow_remote)
                report["stages"]["infrastructure"] = {
                    "status": "succeeded" if m["infrastructure"]["enabled"] else "not_requested",
                    "devcontainer": "generated"
                    if m["infrastructure"]["devcontainer"]
                    else "not_requested",
                    "live_provisioning": "not_requested",
                }
                report["status"] = (
                    "failed" if report["stages"]["remote"].get("ci") == "failed" else "complete"
                )
        except (BootstrapError, OSError, ValueError) as e:
            report["status"] = "failed"
            report["error"] = str(e)
            if isinstance(e, CommandError):
                report["commands"].append(e.result)
        atomic_write(jp, dumps(journal))
        # Omit recovery preimages from terminal output.
        return {k: v for k, v in report.items() if k not in ("applied", "pending")}


def recover(root):
    root = Path(root).resolve()
    jp = within(root, ".bootstrap/local/run.json")
    with execution_lock(root):
        journal = read_json(jp)
        if not journal:
            raise BootstrapError("No run journal")
        if journal.get("stages", {}).get("commit", {}).get("commit"):
            raise BootstrapError(
                "Committed run requires a deliberate Git revert; automatic file recovery refused"
            )
        applied = journal["applied"] + ([journal["pending"]] if journal.get("pending") else [])
        restored = []
        conflicts = []
        for op in reversed(applied):
            p = within(root, op["path"])
            current = file_hash(p)
            if current == op["before"]:
                continue
            if current != op["after"]:
                conflicts.append(op["path"])
                continue
            if op["previous"] is None:
                p.unlink(missing_ok=True)
            else:
                atomic_write(p, op["previous"])
            restored.append(op["path"])
        result = {
            "status": "partial" if conflicts else "complete",
            "restored": restored,
            "conflicts": conflicts,
            "environment_rollback": "not_supported",
            "remote_rollback": "not_performed",
        }
        journal["recovery"] = result
        atomic_write(jp, dumps(journal))
        return result
