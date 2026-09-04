# Analyse Experiment Runbook

## Objective

Identify distinct candidate fault categories from completed experiment artifacts, reconcile each candidate through the [Update Fault Status runbook](update-fault-status-runbook.md), and return portable canonical entries using the [Reconciliation result schema](reconciliation-result-schema.md).

## Guidance

- Establish the experiment identity and comparison constraints from persisted artifacts.
- Compare current correctness, cumulative correctness, regression retention, recovery, integrations, and structural metrics.
- Express candidates as reusable failure modes with one concrete evidence example.
- Compare each candidate’s signal, affected invariant, impact, and remediation target with every existing Fault Category Record; do not stop at likely matches.
- Classify each candidate as a possible existing-category occurrence or a potentially distinct category; do not allocate an ID during analysis.
- For every candidate, retain the exact experiment, checkpoint, harness and pinned revision, agent runtime and version, exact model identifier, reasoning level, artifact path, and concise measured evidence.
- Define a proposed resolution criterion against the broader behavior rather than the example value.
- Before returning any canonical fault name, run every candidate through the [Update Fault Status runbook](update-fault-status-runbook.md) and make its required `create`, `update`, `reopen`, or `no change` decision.
- Return only the reconciled entries defined by the [Reconciliation result schema](reconciliation-result-schema.md). Observations summaries consume these entries and must not coin alternate fault labels.
- Do not produce an experiment-wide summary, own experiment lifecycle work, or mutate catalog records outside the Update Fault Status runbook.
- Validate that candidate claims are artifact-backed and that every existing Fault Category Record was considered for deduplication.
