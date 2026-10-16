# Stack selection and maintenance

The core is language/framework-agnostic; the shipped catalog has explicit coverage.

| Profile | Variants | New-project defaults |
|---|---|---|
| python.library | Python | uv, src package, Ruff, pytest, Hatchling build |
| python.cli | Python | Above, argparse entry point and subprocess behavior test |
| python.fastapi | Python | Above, FastAPI/uvicorn and HTTP health test |
| node.library / node.cli | JavaScript or TypeScript | pnpm or npm, native Node tests, ESLint/Prettier; TS adds tsc/tsx |
| node.express / node.fastify | JavaScript or TypeScript | Explicit framework, HTTP/injection health test |
| web.react-vite | JavaScript or TypeScript | React/Vite, rendering test, production build |
| web.nextjs | JavaScript or TypeScript | Next App Router, health route test, production build |
| existing | Any language | Preserve layout/manifests; infer known scripts or require explicit commands |

Use Python 3.12 and Node 24 as defaults, then honor requirements and compatibility. A helper running under another Python version does not change the project's target. Version constraints live in `assets/catalog/profiles.json`; exact resolved dependency graphs belong in package-manager lockfiles. The helper's direct dependencies are pinned in pyproject.toml. Resolve/install them in an isolated environment; do not install into the user's global interpreter.

Preserve uv, pip requirements, Poetry, npm, pnpm, Yarn, or Bun on adoption. Greenfield templates implement uv and pnpm/npm only. Use explicit command overrides for pip constraints, Poetry dependency groups, Yarn PnP, package-local scripts, or an established monorepo. Never migrate managers silently. Python import names are not PyPI package identities.

A pnpm-only new multi-component project receives a workspace manifest and shared lockfile. Mixed Python/JS projects retain separate environments. `depends_on` orders installation/checks; declare workspace package dependencies explicitly. GitHub CI executes ordered components in one runner, preserving build artifacts. GitLab supports independent mixed-runtime jobs and same-runtime dependency chains; mixed-runtime dependency chains require a reviewed custom image/pipeline overlay.

Generated tests exercise actual scaffold behavior; passing them does not prove the PRD is implemented. TypeScript templates include typecheck; Python type checking is added when requirements select a checker. No fictitious typecheck command is emitted.

Maintain the catalog against official framework/package-manager documentation. Verify Node/Python support, exact action releases, extension IDs, and config semantics before advancing versions. Run the full install/build matrix online on macOS/Linux before declaring a new catalog revision runtime-validated. Record unavailable matrix cells instead of treating syntax/render success as a full install test.
