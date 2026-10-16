# Existing repositories and reorganization

Use `adopt` with profile `existing`. Preserve source, tests, package data, manifests, managers, branch, origin, index, and existing CI. Set ci.provider=none to reuse an existing pipeline unless an additional pipeline is deliberately required. The scanner prunes caches during traversal and treats editor/harness files as inputs.

Read scripts and configuration before trusting inferred command names. Existing package scripts may be watch commands, placeholders, or side-effectful; override them with real terminating checks. Missing verification is a gap to resolve, not a reason to invent success. Python pytest/Ruff detection is conservative; override nonstandard tool groups or paths explicitly.

README, AGENTS, CLAUDE, decisions, and gitignore additions use marked regions. Unmanaged text remains outside the region. Managed files update only when the previous content matches ownership records. Existing JSON is merged additively, with named task/config conflicts surfaced; JSONC comments are never discarded. Existing CI and Codex config are preserved. Do not change or remove ownership records to force a replacement.

Use `reorganize` only for an explicit user request or requirement that cannot be met by adoption. Supply individual text-file moves, absent destinations, and a reason. Binary assets and directory trees require a separate reviewed migration. A destination cannot also be produced by a conflicting template. Do not move a source document used to validate the current plan; move it in a separate step and update provenance.

Before relocation, map imports, entry points, package data, relative resource lookup, and pytest conftest scopes. Prefer multiple small migrations with checks between them. There is no automatic blanket move of Python source or tests. Existing file paths and scoped conftest behavior are part of the project's contract.

`git.additional_paths` names authored files intentionally included in a requested commit. New scaffolds stage only generated files and actual lockfiles, not every untracked file. A pre-existing staged index defers the commit with a failed stage; it is not silently included. Do not change global identity or force-push.
