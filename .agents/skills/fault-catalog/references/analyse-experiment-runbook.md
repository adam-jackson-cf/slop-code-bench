# Analyse Experiment Runbook

## Objective

Extract distinct fault categories from experiment evidence and append new evidence to existing Fault Category Records.

## Guidance

- Establish the experiment identity and comparison constraints from persisted artifacts.
- Compare current correctness, cumulative correctness, regression retention, recovery, integrations, and structural metrics.
- Express candidates as reusable failure modes with one concrete evidence example.
- Compare each candidate’s signal, affected invariant, impact, and remediation target with every existing Fault Category Record.
- Classify each candidate as a possible existing-category occurrence or a potentially distinct category; do not allocate an ID during analysis.
- For every candidate, retain the exact experiment, checkpoint, harness and pinned revision, agent runtime and version, exact model identifier, reasoning level, artifact path, and concise measured evidence.
- Define a proposed resolution criterion against the broader behavior rather than the example value.
- Use the [Update Fault Status runbook](update-fault-status-runbook.md) to make the strict create, update, reopen, or no-change decision and apply catalog changes.
- Validate that candidate claims are artifact-backed and that potentially matching existing records were considered.
