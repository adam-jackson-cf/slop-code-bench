# Status Matrix Runbook

## Objective

Report execution state for every matrix member without interpreting experiment behavior or completion quality.

## Procedure

1. Inspect every configured matrix member through its persisted process state and artifacts.
2. Report only execution facts: member identity, state, current or last checkpoint, completed checkpoint count, elapsed time, failure or stop signal, token usage, and estimated API-equivalent cost when available.
3. Label a completed checkpoint count as execution coverage, not correctness. Distinguish estimated API-equivalent cost from actual subscription billing.
4. Do not classify faults, assess pass quality, determine completion, compare models, recommend improvements, or produce a user result template.

## Output

Return a concise execution-state listing. Route a fully terminal matrix to the terminal handoff runbook.
