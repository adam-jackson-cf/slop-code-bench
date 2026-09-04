---
name: "full-suite-matrix"
description: "Control full-suite benchmark matrix execution and terminal artifact handoff. USE WHEN initiating, checking status for, resuming, stopping, restarting, or handing off a full-suite benchmark matrix."
---

# Task

- Resolve repository-provided values from current configuration, experiment records, and runtime state instead of asking the user.
- When a required tool presents choices, select its recommended option as already approved by the user.
- Ask only when no recommended option exists and repository evidence cannot resolve materially different choices.
- Follow the runbook that matches the requested lifecycle action:
  - [Initiate a matrix run](references/initiate-matrix-runbook.md)
  - [Check matrix status](references/status-matrix-runbook.md)
  - [Resume, stop, or restart a matrix member](references/control-matrix-runbook.md)
  - [Hand off terminal matrix artifacts](references/terminal-handoff-runbook.md)
