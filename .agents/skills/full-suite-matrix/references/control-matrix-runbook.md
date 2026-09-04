# Control Matrix Runbook

## Objective

Resume, stop, or restart an identified matrix member while preserving its baseline artifacts.

## Procedure

1. Resolve the exact matrix member and requested control action from runtime state and repository records.
2. Resume only through the harness-supported resume path and retain the member's original resolved configuration.
3. Before stopping or restarting, preserve completed artifacts. Never delete, overwrite, or reuse a prior baseline output directory or mutable workspace.
4. For restart, create the required distinct output location and record the new execution identity while retaining the original artifacts.
5. Use the repository's persistent long-running process convention for resume or restart.

## Output

Report the requested control action, affected member, resulting execution state, and relative artifact location. Use the status runbook for later progress requests.
