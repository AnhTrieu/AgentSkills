# Failure and recovery

Plan outside the target. Applying verifies input and destination hashes, rejects conflicts, and takes an exclusive execution lock. Each file operation is journaled before mutation; successful writes record preimages. Never run two helpers against the same target concurrently.

- Use `resume --plan /absolute/plan.json` after resolving an unavailable tool or interrupted operation. The plan digest must match the journal; affected files must match recorded postimages. Installs and checks rerun to reconcile real state.
- Use `recover /absolute/root` to restore unmodified generated files from journaled preimages. Modified files become conflicts; they are not overwritten. A recovered run needs a new plan.
- Replan when inputs, requirements, templates, or commands change. Preserve failed-run evidence until recovery/replanning is understood.

Recovery is file-scoped. It does not remove installed packages, remove a newly initialized .git, revert a commit, undo a remote push, or destroy resources. A committed run requires deliberate Git revert/reconciliation. Formatters or generators may change files after write journaling; if those changes cannot be matched safely, recovery reports conflicts.

The helper stops on install/check failure before commit or remote mutation. It returns nonzero for failure/conflicts. `--files-only` reports partial because dependency/environment verification was not performed. Missing editor executables or authentication remains an explicit failure for requested steps. Optional capabilities report not_requested. Remote CI is observed once and may be not_run or pending; it is never inferred from local success.

After successful installation, unchanged template inputs preserve formatter-normalized output on rerun. User-edited generated files require reconciliation. Template upgrades are reviewed plans, not silent overwrites.
