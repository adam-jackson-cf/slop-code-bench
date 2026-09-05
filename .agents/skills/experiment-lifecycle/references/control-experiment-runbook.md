# Control Experiment Runbook

## Objective

Resume, stop, or restart an identified execution while preserving its evidence.

## Procedure

1. Resolve the exact execution and requested action from process state and repository records.
2. Resume only through the harness-supported resume path and retain the original resolved configuration, output directory, and mutable workspace.
3. Before stopping, preserve completed artifacts and record the resulting terminal state.
4. Restart as a new execution with a distinct output location and process identity. Retain the original execution and artifacts unchanged.
5. Use the current environment's persistent process mechanism for resume or restart.
6. Never delete, overwrite, or repurpose an existing experiment directory.

## Output

Report the action, affected execution, resulting state, process identity, and repository-relative artifact location. Use the status runbook for later checks.
