# Select Experiment Target Runbook

## Objective

Select and prepare an unresolved Fault Category Record for a future experiment.

## Guidance

- Follow the [Fault Category Record schema](fault-category-record-schema.md) for canonical statuses and integrity rules.
- Consider records with `open` or `reopened` status.
- Rank candidates by cumulative impact, recurrence, and whether a controlled intervention is measurable.
- Prefer one fault category with a clear causal hypothesis over changing several variables.
- Record the experiment identifier, objective, declared intervention variable, expected values, fixed controls, and unchanged resolution criterion before execution.
- Transition the selected record to `targeted` in the catalog index and Fault Category Record.
- Append a dated history entry recording the prior status and selection rationale.
- Do not claim that selecting a fault category mitigates or resolves it.
- Validate the transition, experiment reference, intervention, criterion, and index synchronization.
- Hand the recorded target to `experiment-lifecycle` for preflight and execution; target selection does not launch an experiment.
