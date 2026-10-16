from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile


class BootstrapError(Exception):
    pass


class CommandError(BootstrapError):
    def __init__(self, result):
        self.result = result
        super().__init__("Command failed: " + result["id"])


def sha(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def relative(path):
    if (
        not isinstance(path, str)
        or not path
        or "\\" in path
        or "\x00" in path
        or "\n" in path
        or "\r" in path
    ):
        raise BootstrapError("Invalid relative path")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or ":" in path or path.startswith("-"):
        raise BootstrapError("Path escapes root or is not portable: " + path)
    if any(x.lower() == ".git" for x in p.parts):
        raise BootstrapError("Git internals cannot be a managed output")
    return p.as_posix()


def within(root, rel):
    rel = relative(rel)
    root = Path(root).resolve()
    p = root / rel
    for part in [p, *p.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise BootstrapError("Symlink path rejected: " + rel)
    if not p.resolve().is_relative_to(root):
        raise BootstrapError("Path escapes root: " + rel)
    return p


def file_hash(p):
    if p.exists() and not p.is_file():
        raise BootstrapError("Expected file: " + str(p))
    return sha(p.read_bytes()) if p.exists() else None


def atomic_write(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name + ".", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as h:
            h.write(content)
        if p.exists():
            os.chmod(tmp, p.stat().st_mode & 0o777)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def redact(text):
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(
        r"(?i)((?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", text
    )
    for k, v in os.environ.items():
        if len(v) > 5 and re.search(r"TOKEN|PASSWORD|SECRET|API_KEY|AUTHORIZATION", k, re.I):
            text = text.replace(v, "[redacted]")
    return text


def run_command(command, root):
    argv = command["argv"]
    cwd = within(root, command.get("cwd", "."))
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(a, str) and "\x00" not in a for a in argv)
    ):
        raise BootstrapError("Invalid argv")
    result = {
        "id": command.get("id", "command"),
        "argv": [redact(a) for a in argv],
        "cwd": command.get("cwd", "."),
        "status": "failed",
    }
    try:
        p = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=command.get("timeout", 180),
            env=os.environ.copy(),
        )
        result.update(
            returncode=p.returncode,
            stdout=redact(p.stdout[-4000:]),
            stderr=redact(p.stderr[-4000:]),
        )
        if p.returncode:
            raise CommandError(result)
    except (OSError, subprocess.TimeoutExpired) as e:
        result.update(returncode=None, error=redact(str(e)))
        raise CommandError(result) from e
    result["status"] = "succeeded"
    return result


def command(id, argv, cwd=".", timeout=180, **kwargs):
    return {"id": id, "argv": [redact(a) for a in argv], "cwd": cwd, "timeout": timeout, **kwargs}
