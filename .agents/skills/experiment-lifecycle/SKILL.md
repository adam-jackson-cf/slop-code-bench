---
name: "experiment-lifecycle"
description: "Use when starting, operating, or handing off a benchmark experiment."
---

# Experiment lifecycle

Use the existing run configuration and persisted resolved artifacts as the canonical experiment definition. Do not create a parallel manifest or configuration format.

Choose the runbook matching the requested lifecycle action:

- [Initiate an experiment](references/initiate-experiment-runbook.md)
- [Check experiment status](references/status-experiment-runbook.md)
- [Resume, stop, or restart an experiment](references/control-experiment-runbook.md)
- [Hand off terminal artifacts](references/terminal-handoff-runbook.md)
- [Handle experiment errors](references/error-experiment-runbook.md)

Model unavailability or harness failures cause immediate stopping of an experiment and must surface to the user.

Resolve repository-provided values from current configuration, experiment records, and runtime state. Ask only when those sources cannot resolve a materially different choice.
