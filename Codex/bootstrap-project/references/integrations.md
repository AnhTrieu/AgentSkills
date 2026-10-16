# Editor, harness, and CI adapters

Generate only configured tool capabilities. Python recommends the Python/Pylance/debugpy extensions and Ruff when configured. JS/TS recommends ESLint/Prettier when present. Tasks use process argv, component working directories, and workspace-relative paths. New Python profiles use their component .venv interpreter. Poetry interpreter location remains user/project-managed. Multi-root workspaces name the repository folder so root tasks remain unambiguous.

Extension recommendations do not install software. Installation requires `extension_installation=install` and a named VS Code profile. Keep shared .vscode files tracked, local machine state excluded, and existing configuration intact. Do not disable workspace trust or security to activate tasks.

Canonical instructions live in AGENTS.md. Matching component scopes are generated for multi-component repositories. Claude receives an actual `@AGENTS.md` import and a verification skill generated from the same template. Codex uses `.agents/skills`, root/component AGENTS, and a comment-only `.codex/config.toml` unless an existing file is preserved. Antigravity uses shared `.agents/skills`; add `.agents/rules` only for real additional scoped rules with documented activation metadata. Empty directories alone do not enable integrations. Ownership/template hashes detect drift in generated copies.

GitHub Actions uses pinned released tags, read-only content permissions, cancellation groups, lockfile-aware installs, and project commands. Hosted runners are default; self-hosted macOS must be selected. GitLab pipelines retain the selected package manager. Existing CI is preserved, not silently replaced. A preserved pipeline must be reviewed against the new command model; do not claim it verifies newly added components automatically.

Official references checked during implementation (recheck when maintaining adapters):

- https://code.visualstudio.com/docs/configure/extensions/extension-marketplace
- https://code.visualstudio.com/docs/editing/workspaces/workspaces
- https://developers.openai.com/codex/guides/agents-md/
- https://developers.openai.com/codex/config-basic/
- https://developers.openai.com/codex/skills/
- https://code.claude.com/docs/en/memory
- https://antigravity.google/docs/rules/
- https://antigravity.google/docs/skills/
- https://antigravity.google/docs/ide/workflows/
- https://jinja.palletsprojects.com/en/stable/api/
- https://docs.astral.sh/uv/concepts/projects/sync/
- https://pnpm.io/cli/install

Static file validation and unit tests do not establish live IDE discovery, debugger connections, extension installation, or passing remote CI. Report those separately.
