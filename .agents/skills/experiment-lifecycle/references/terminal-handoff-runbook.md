# Terminal Handoff Runbook

## Objective

Hand verified terminal artifacts to `experiment-observations` without interpreting experiment quality.

## Preconditions

- Every configured execution has reached a canonical terminal state.
- Each execution retains readable, repository-relative paths to its resolved configuration and required evidence.

## Procedure

1. Enumerate executions from the resolved run configurations and verify each terminal state.
2. Verify repository-relative paths for the resolved configuration, run provenance, run summary, checkpoint results, every configured checkpoint evaluation, quality metrics, and telemetry needed for a claim.
3. Accept a manifest as an inventory only after every enumerated path resolves to the corresponding readable artifact.
4. For a comparison, verify every fixed control is equivalent. Verify the declared experimental variable has the expected value for each member; do not require that variable itself to be equivalent.
5. Do not assess completion quality, classify faults, compare behavior, or compose user-facing observations.

## Handoff

Provide `experiment-observations`:

- the objective, declared experimental variable and values, and fixed controls;
- each experiment identifier and canonical terminal state;
- repository-relative paths to resolved configuration, provenance, summary, checkpoint results, quality metrics, and required telemetry; and
- checkpoint-keyed repository-relative paths to per-checkpoint evaluations.

If an execution is non-terminal or required evidence is unavailable, report that fact and do not hand it off as complete.
