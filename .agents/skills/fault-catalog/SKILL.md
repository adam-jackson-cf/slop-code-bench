---
name: "fault-catalog"
description: "Maintain the experiment fault catalog consistently. USE WHEN extracting fault types from experiments, updating fault status, or selecting the next fault to target."
---

# Task

## Inputs

- Read `experiment_analysis/fault-catalog.md` before changing it.
- Treat persisted experiment artifacts as authoritative.
- Load only the runbook required for the requested action.
- Use the [Fault Category Record schema](references/fault-category-record-schema.md) for canonical paths, fields, statuses, and integrity rules.
- Use the [Reconciliation result schema](references/reconciliation-result-schema.md) when returning reconciled fault entries to a consumer.

## Actions

- [Analyse an experiment](references/analyse-experiment-runbook.md) to identify candidate fault categories and occurrences from artifact evidence, deduplicate them against every existing Fault Category Record, and coordinate reconciliation.
- [Reconcile experiment evidence](references/update-fault-status-runbook.md) to create records, update occurrences, and apply strict status transitions.
- [Select an experiment target](references/select-experiment-target-runbook.md) from unresolved Fault Category Records.

## Catalog Integrity

- Preserve canonical Fault Category Record IDs and wording.
- Keep the catalog index and linked Fault Category Records synchronized.
- Deduplicate failure modes; never create one record per failed assertion.
- Track every observed experiment, harness revision, agent runtime, exact model, and reasoning level on the relevant record.
- Preserve historical evidence and resolved Fault Category Records.

## Validation

- Verify statuses, transitions, evidence, and index consistency.
- Report changed Fault Category Record IDs, resulting statuses, and evidence paths.
