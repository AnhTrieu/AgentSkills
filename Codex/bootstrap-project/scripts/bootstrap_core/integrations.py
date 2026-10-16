from __future__ import annotations
import json
import shlex
from .model import CHECKS
from .util import BootstrapError, CommandError, command, run_command, within

ACTIONS = {
    "checkout": "actions/checkout@v7.0.1",
    "node": "actions/setup-node@v7.1.0",
    "python": "actions/setup-python@v7.0.0",
    "uv": "astral-sh/setup-uv@v10.3.0",
    "pnpm": "pnpm/action-setup@v6.1.0",
}


def shell(cmd):
    return shlex.join(cmd["argv"])


def ci_config(m):
    provider = m["ci"]["provider"]
    jobs = {}
    allpnpm = (
        m["project"]["mode"] == "init"
        and len(m["components"]) > 1
        and all(c["package_manager"] == "pnpm" for c in m["components"])
    )
    for c in m["components"]:
        py = c["language"] == "python"
        pm = c["package_manager"]
        steps = [{"uses": ACTIONS["checkout"]}]
        before = []
        if py:
            steps.append(
                {"uses": ACTIONS["python"], "with": {"python-version": c["python_version"]}}
            )
            if pm == "uv":
                steps.append(
                    {
                        "uses": ACTIONS["uv"],
                        "with": {
                            "enable-cache": True,
                            "cache-dependency-glob": c["path"] + "/uv.lock",
                        },
                    }
                )
                before.append("python -m pip install uv==0.9.5")
            elif pm == "poetry":
                install = "python -m pip install poetry==" + (c["manager_version"] or "2.2.1")
                steps.append({"name": "Install Poetry", "run": install})
                before.append(install)
        elif c["language"] in ("javascript", "typescript"):
            if pm == "pnpm":
                steps.append(
                    {
                        "uses": ACTIONS["pnpm"],
                        "with": {"version": c["manager_version"] or "10.20.0"},
                    }
                )
            cache = (
                {
                    "cache": pm,
                    "cache-dependency-path": (
                        "pnpm-lock.yaml"
                        if allpnpm
                        else ("" if c["path"] == "." else c["path"] + "/")
                        + {
                            "pnpm": "pnpm-lock.yaml",
                            "npm": "package-lock.json",
                            "yarn": "yarn.lock",
                        }[pm]
                    ),
                }
                if pm in ("pnpm", "npm")
                else {}
            )
            steps.append(
                {"uses": ACTIONS["node"], "with": {"node-version": c["node_version"], **cache}}
            )
            if pm == "pnpm":
                before.append("npm install --global pnpm@" + (c["manager_version"] or "10.20.0"))
            elif pm in ("yarn", "bun"):
                if not c["manager_version"]:
                    raise BootstrapError("CI for Yarn/Bun requires explicit manager_version")
                install = (
                    (
                        "corepack enable && corepack prepare yarn@"
                        + c["manager_version"]
                        + " --activate"
                    )
                    if pm == "yarn"
                    else ("npm install --global bun@" + c["manager_version"])
                )
                steps.append({"name": "Install manager", "run": install})
                before.append(install)
        elif m["ci"]["provider"] != "none":
            raise BootstrapError(
                "Custom-language CI needs an explicit provider overlay and ci.provider=none"
            )
        sequence = []
        if "prepare" in c["commands"]:
            sequence.append(c["commands"]["prepare"])
        sequence.append(c["commands"].get("ci_install", c["commands"].get("install")))
        sequence += [c["commands"][k] for k in CHECKS if k in c["commands"]]
        sequence = [x for x in sequence if x]
        if provider == "github":
            for cmd in sequence:
                steps.append({"name": cmd["id"], "working-directory": c["path"], "run": shell(cmd)})
            jobs[c["id"]] = {
                "runs-on": ["self-hosted", "macOS"]
                if m["ci"]["runner"] == "self_hosted_macos"
                else "ubuntu-latest",
                "steps": steps,
            }
            if c["depends_on"]:
                jobs[c["id"]]["needs"] = c["depends_on"]
        else:
            jobs[c["id"]] = {
                "image": "python:" + c["python_version"] + "-slim"
                if py
                else "node:" + c["node_version"],
                "stage": "verify",
                "before_script": before,
                "script": ["cd " + shlex.quote(c["path"])] + [shell(x) for x in sequence],
            }
            if c["depends_on"]:
                jobs[c["id"]]["needs"] = c["depends_on"]
    if provider == "gitlab":
        import copy

        originals = copy.deepcopy(jobs)
        by_id = {c["id"]: c for c in m["components"]}
        for c in m["components"]:
            wanted = set()

            def include(cid):
                for dep in by_id[cid]["depends_on"]:
                    include(dep)
                wanted.add(cid)

            include(c["id"])
            chain = [x for x in m["components"] if x["id"] in wanted]
            if len({x["language"] == "python" for x in chain}) > 1:
                raise BootstrapError(
                    "Mixed-language GitLab dependency chains need a custom image/pipeline overlay"
                )
            if len(chain) > 1:
                jobs[c["id"]]["before_script"] = list(
                    dict.fromkeys(
                        step for x in chain for step in originals[x["id"]]["before_script"]
                    )
                )
                jobs[c["id"]]["script"] = ['cd "$CI_PROJECT_DIR"']
                for x in chain:
                    jobs[c["id"]]["script"].extend(originals[x["id"]]["script"])
                    jobs[c["id"]]["script"].append('cd "$CI_PROJECT_DIR"')
    if provider == "github" and len(jobs) > 1:
        ordered_steps = [{"uses": ACTIONS["checkout"]}]
        for job in jobs.values():
            ordered_steps.extend(job["steps"][1:])
        jobs = {
            "workspace": {"runs-on": next(iter(jobs.values()))["runs-on"], "steps": ordered_steps}
        }
    if provider == "github":
        return ".github/workflows/bootstrap-ci.yml", {
            "name": "Project checks",
            "on": {"push": {}, "pull_request": {}},
            "permissions": {"contents": "read"},
            "concurrency": {
                "group": "${{ github.workflow }}-${{ github.ref }}",
                "cancel-in-progress": True,
            },
            "jobs": jobs,
        }
    return ".gitlab-ci.yml", {"stages": ["verify"], **jobs}


def git_root(root):
    try:
        return run_command(command("git:root", ["git", "rev-parse", "--show-toplevel"]), root)[
            "stdout"
        ].strip()
    except CommandError:
        return None


def init_git(root, policy):
    current = git_root(root)
    if current and str(within(root, ".")) != current:
        raise BootstrapError("Target is inside another repository; choose the repository root")
    if current:
        return {"status": "succeeded", "created": False}
    if not policy["initialize"]:
        return {"status": "not_requested", "created": False}
    run_command(command("git:init", ["git", "init", "-b", policy["initial_branch"]]), root)
    return {"status": "succeeded", "created": True}


def commit_files(root, paths, policy, created):
    wanted = policy["commit"] == "after_verification" or (
        created and policy["commit"] == "new_repo_after_verification"
    )
    if not wanted:
        return {"status": "not_requested"}
    staged = run_command(command("git:staged", ["git", "diff", "--cached", "--name-only"]), root)[
        "stdout"
    ]
    if staged.strip():
        raise BootstrapError("Pre-existing staged changes: commit deferred to preserve the index")
    for field in ["user.name", "user.email"]:
        try:
            run_command(command("git:identity", ["git", "config", "--get", field]), root)
        except CommandError as e:
            raise BootstrapError("Git identity missing; configure it before committing") from e
    selected = []
    from scan_project import is_secret

    for p in sorted(set(paths + policy["additional_paths"])):
        target = within(root, p)
        if not target.is_file():
            tracked = run_command(command("git:tracked", ["git", "ls-files", "--", p]), root)[
                "stdout"
            ].strip()
            if not tracked:
                continue
        if is_secret(p) or p.startswith(".bootstrap/local/"):
            raise BootstrapError("Private path cannot be committed: " + p)
        selected.append(p)
    if not selected:
        return {"status": "succeeded", "commit": None}
    # Snapshot only the index before staging. Failed commit restores this snapshot.
    index_rel = run_command(
        command("git:index", ["git", "rev-parse", "--git-path", "index"]), root
    )["stdout"].strip()
    from pathlib import Path

    index = Path(index_rel)
    index = index if index.is_absolute() else root / index
    previous = index.read_bytes() if index.exists() else None
    try:
        run_command(command("git:stage", ["git", "add", "--", *selected]), root)
        changed = run_command(
            command("git:staged", ["git", "diff", "--cached", "--name-only"]), root
        )["stdout"].strip()
        if not changed:
            return {"status": "succeeded", "commit": None}
        run_command(
            command(
                "git:commit", ["git", "commit", "-m", "Bootstrap project development workspace"]
            ),
            root,
        )
    except Exception:
        if previous is None:
            index.unlink(missing_ok=True)
        else:
            index.write_bytes(previous)
        raise
    return {
        "status": "succeeded",
        "commit": run_command(command("git:head", ["git", "rev-parse", "HEAD"]), root)[
            "stdout"
        ].strip(),
    }


def remote_apply(root, policy, authorized):
    if policy["mode"] == "none":
        return {"status": "not_requested"}
    if not authorized:
        raise BootstrapError(
            "Remote operations need current-session authorization; pass --allow-remote when already authorized"
        )
    url = policy.get("url") or "https://github.com/" + policy["repository"] + ".git"

    def call(id, args):
        return run_command(command(id, args), root)

    try:
        old = call("remote:origin", ["git", "remote", "get-url", "origin"])["stdout"].strip()
    except CommandError:
        old = None

    def identity(s):
        return s.removesuffix(".git").replace("git@github.com:", "https://github.com/")

    if old and identity(old) != identity(url):
        raise BootstrapError("Existing origin differs; it will not be replaced")
    if policy["mode"] == "create":
        try:
            info = json.loads(
                call(
                    "remote:inspect",
                    [
                        "gh",
                        "repo",
                        "view",
                        policy["repository"],
                        "--json",
                        "nameWithOwner,visibility",
                    ],
                )["stdout"]
            )
        except CommandError as e:
            if "Could not resolve to a Repository" not in e.result.get(
                "stderr", ""
            ) and "404" not in e.result.get("stderr", ""):
                raise
            call(
                "remote:create",
                ["gh", "repo", "create", policy["repository"], "--" + policy["visibility"]],
            )
            info = json.loads(
                call(
                    "remote:inspect",
                    [
                        "gh",
                        "repo",
                        "view",
                        policy["repository"],
                        "--json",
                        "nameWithOwner,visibility",
                    ],
                )["stdout"]
            )
        if info["visibility"].lower() != policy["visibility"]:
            raise BootstrapError("Existing repository visibility differs from requested visibility")
    # Read remote refs before linking/pushing. A normal push will reject incompatible history.
    call("remote:refs", ["git", "ls-remote", url])
    if not old:
        call("remote:link", ["git", "remote", "add", "origin", url])
    report = {"status": "succeeded", "url": url, "push": "not_requested", "ci": "not_run"}
    if policy["push"]:
        branch = call("remote:branch", ["git", "branch", "--show-current"])["stdout"].strip()
        if not branch:
            raise BootstrapError("Cannot push detached HEAD")
        call("remote:push", ["git", "push", "--set-upstream", "origin", branch])
        report["push"] = "succeeded"
        if policy.get("repository"):
            head = call("remote:head", ["git", "rev-parse", "HEAD"])["stdout"].strip()
            runs = json.loads(
                call(
                    "remote:ci",
                    [
                        "gh",
                        "run",
                        "list",
                        "--repo",
                        policy["repository"],
                        "--commit",
                        head,
                        "--json",
                        "status,conclusion,url",
                    ],
                )["stdout"]
            )
            report["ci"] = (
                "not_run"
                if not runs
                else "pending"
                if any(x["status"] != "completed" for x in runs)
                else "passed"
                if all(x["conclusion"] == "success" for x in runs)
                else "failed"
            )
            report["runs"] = runs
    return report
