# Initiate Experiment Runbook

## Objective

Start one benchmark run or an equivalent-run matrix from repository configuration without creating a second experiment-definition format.

## Procedure

1. State the experiment objective. For a comparison, identify the single declared experimental variable and its requested values.
2. Resolve the fixed controls from run configuration and prior records: problem set and revision, seed, agent harness and version, runner revision, environment, prompt, reasoning level, checkpoint sequence, assessment policy, continuation behavior, model identity, pricing metadata, and output configuration.
3. Keep every fixed control equivalent across comparison members. The declared experimental variable may differ; model identity is a fixed control only when it is not that variable.
4. Use `assessment_policy: all-cases`. Set `continue_after_test_failure: true` only for a longitudinal experiment that must execute later checkpoints after a failed assessment.
5. Verify required credentials by presence only. Verify the container runtime, pinned agent version, model configuration, problem revision, and a unique output location for every execution.
6. Preflight the exact resolved invocation with `uv run slop-code run ... --dry-run`. Stop on any configuration, credential, problem-resolution, or output collision error.
7. Launch the same invocation without `--dry-run` through the current environment's persistent process mechanism. Independent matrix members may run concurrently when capacity permits.
8. Do not switch a member's model, controls, output directory, or mutable workspace during a cumulative run.
9. Confirm each process is running and has persisted its resolved configuration and initial run metadata before reporting that it started.

## Output

Report the objective, declared variable, fixed controls, execution identifiers, process identifiers, and repository-relative output locations. Use the status runbook for subsequent progress checks.
