# Manifest and command contract

Use `assets/schemas/project.schema.json` as the exact schema. Unknown keys are rejected. The examples are valid starting points, not instructions to retain placeholder decisions.

Required root keys: `schema_version: 1`, `project`, `components`. Project requires a kebab-case name, description, and mode (`init`, `adopt`, `reorganize`). Each component needs a unique id, relative path, language, profile, and package_manager. Multiple components occupy separate nonoverlapping subdirectories; a single component can use `.`.

Optional fields:

| Field | Meaning |
|---|---|
| sources | `{path, kind, sha256?}`; kind is prd/sdd/adr/readme/other; paths inside root; hash computed and checked during planning |
| decisions | `{choice, reason, source, inferred?}`; cite a document section or current user requirement |
| components[].depends_on | Component IDs in dependency order; cycles and unknown IDs rejected; shared code dependencies still need manifest declarations |
| runtime_deps / dev_deps | Python requirement strings, deliberately separated |
| npm_dependencies / npm_dev_dependencies | Package-name to version maps; required workspace dependencies must be explicit |
| commands | Named command overrides `{argv: [executable, arg, ...], timeout?: seconds}`; shell syntax is not implicitly interpreted |
| editor | enabled, single_folder/multi_root layout, recommend_only/install extensions, optional profile |
| harnesses | Any subset of claude_code, codex, antigravity; empty disables harness-specific files |
| git | initialize, initial_branch, commit policy, explicit additional_paths for authored files to commit |
| ci | provider none/github/gitlab; runner hosted/self_hosted_macos |
| remote | mode none/link/create; provider github; repository owner/name or URL; visibility private/public; push boolean |
| infrastructure | enabled; devcontainer; image; ports; provider is reserved and fails until a named adapter exists |
| deviations | Unique id, requirement, reason, validation; explain why normal template parameters cannot meet the requirement |
| overlays | path, literal content, deviation id; content is reproducible, not evaluated as Jinja |
| moves | source, destination, reason; only reorganize mode, text files, destination absent |

All paths are relative POSIX paths within the root. Reject symlinks, traversal, Git internals, credential-like outputs, and secret source documents. The helper can only detect known secret patterns; the agent must review content before committing. Keep credentials out of argv, templates, and JSON. Commands inherit the caller's environment; use environment variable names in documentation rather than values.

Capabilities: install, ci_install, lock, format_check, format_fix, lint, typecheck, test, build, dev, smoke. Explicit commands are used for atypical projects and unknown languages. Existing/custom components require at least one real verification command. The core does not infer product architecture or parse free-form PRDs deterministically.

For a Rust repository, use language=rust, profile=existing, package_manager=cargo, explicit `cargo test` and `cargo build` commands, and ci.provider=none unless providing a deliberate CI overlay. For an unsupported new stack, supply reviewed source/config overlays and explicit commands against an existing component directory. Record the compatibility requirement; do not label the result a tested catalog template.

The generated `.bootstrap/project.json` retains the source manifest. `.bootstrap/template-lock.json` records the template digest and profile revisions; `.bootstrap/managed-files.json` tracks ownership and template inputs. These are portable and tracked. Execution plans contain absolute target paths and are local review artifacts; journals under `.bootstrap/local/` contain recovery preimages and are ignored.

Commands in README, AGENTS, VS Code, and CI derive from one normalized model. Plans are executable artifacts: read all commands and diff content before applying. Neither hashes nor schema validation grant permission to execute commands embedded in an untrusted manifest.
