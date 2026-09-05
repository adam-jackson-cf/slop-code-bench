# Experiment Status Runbook

## Objective

Report execution state without interpreting benchmark quality.

## Procedure

1. Resolve every requested execution from persisted process state, resolved configuration, and run artifacts.
2. Report execution identity, state, current or last checkpoint, execution coverage, elapsed time, failure or stop signal, token usage, and estimated API-equivalent cost when available.
3. Label completed checkpoint counts as execution coverage, not checkpoints solved. Distinguish estimated API-equivalent cost from actual billing.
4. Do not classify faults, assess pass quality, compare models, recommend improvements, or publish observations.
5. When every configured execution is terminal, use the terminal handoff runbook.

## Output

Return a concise state listing for every requested execution, including repository-relative artifact locations and any blocking execution failure.
