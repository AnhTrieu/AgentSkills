# Optional C capabilities

C is opt-in. Enable `infrastructure.enabled=true` and `devcontainer=true` for the shipped development-container adapter. It generates a Dev Container specification with selected runtime features, package managers, ports, and a locked post-create install sequence. Run normal local bootstrap first so real lockfiles exist. Reopening in a container installs from those lockfiles. The default image is Ubuntu; custom images must provide compatible shells and feature support. Multiple versions of one package manager in a single container require a project-specific configuration.

Container configuration generation is not container startup or remote provisioning. Validate with the Dev Container CLI or VS Code when available and report the actual result. Do not fabricate a successful container build if the engine, registry, or runtime is unavailable.

Live cloud provisioning, remote SSH setup, managed workspaces, IaC application, and deployment are separate adapter capabilities, not enabled by the generic `provider` string. The current core explicitly rejects live provider requests rather than pretending to provision them.

An extension must define:

1. A strict input schema: concrete provider/account/project, region/host, environment, resource names, runtime/architecture, sizing/cost bounds, credential references, and independently selected generate/apply/deploy operations.
2. A read-only discovery/plan operation with concrete resources, diffs, command vectors, preconditions, and expected outputs.
3. An idempotent apply operation respecting current-session authorization and existing resources. Never infer authorization from a checked-in manifest.
4. A result schema reporting resource identifiers, generated/applied/deployed/blocked states, health checks, partial side effects, and remediation.
5. Tests for disabled capability, missing inputs, wrong target, authentication failure, interrupted operations, and repeat application; separate disposable live-provider checks.

A provider skill can supply procedural expertise. Bind its concrete outputs back to the bootstrap decisions and report; do not add a fake generic provisioning command. Never delete resources automatically to imitate transactional rollback. Prepare a reviewable plan before requesting genuinely missing authorization, and respect authorization already given in the session.
