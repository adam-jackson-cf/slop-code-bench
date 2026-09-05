# experiment-lifecycle

## Overview

Defines, preflights, launches, monitors, controls, and hands off single-run or matrix benchmark experiments. Existing run configuration and persisted artifacts remain the canonical experiment record.

## When to use it

- Start a benchmark experiment or equivalent-run matrix.
- Check, resume, stop, or restart an execution.
- Verify terminal artifacts before analysis.
- Handle model unavailability or harness failures.

## Example prompts

- "Preflight and start this experiment."
- "Check the status of every run in this matrix."
- "Hand the completed experiment to observations."

## References

- [Initiate an experiment](references/initiate-experiment-runbook.md)
- [Check experiment status](references/status-experiment-runbook.md)
- [Control an experiment](references/control-experiment-runbook.md)
- [Hand off terminal artifacts](references/terminal-handoff-runbook.md)
- [Handle experiment errors](references/error-experiment-runbook.md)
