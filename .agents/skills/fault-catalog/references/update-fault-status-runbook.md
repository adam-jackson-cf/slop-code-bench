# Update Fault Status Runbook

## Objective

Reconcile experiment evidence against the fault catalog by making exactly one decision for each evidenced failure mode: create a Fault Category Record, update an existing record, reopen a resolved record, or make no catalog change.

## Preconditions

- Read the catalog, every potentially matching Fault Category Record, and the [Fault Category Record schema](fault-category-record-schema.md).
- Use persisted experiment artifacts as evidence. An observations file may identify candidates but cannot independently justify creation or a status change.
- Establish the experiment identifier, checkpoint, harness revision, agent runtime and version, exact model, reasoning level, fixture, seed, pass policy, and intervention.
- Compare equivalent metrics and checkpoint scopes. Do not compare isolated correctness with cumulative correctness or substitute aggregate averages for final retention.
- Do not change a status when required evidence, the original resolution criterion, or the comparison baseline is unavailable.

## Decide Whether to Create or Update

Evaluate existing records before allocating an ID.

### Update an existing record

Update an existing Fault Category Record when the new evidence has the same:

- recurring failure mode;
- detection signal or an equivalent measurement of that signal;
- affected behavioral or structural invariant;
- remediation target represented by the existing resolution criterion.

A different model, reasoning level, harness, checkpoint, severity, or failed assertion is a new occurrence of the same category unless the underlying invariant and remediation target are materially different.

When the category already exists:

1. Append one observed-configuration row for each newly evidenced configuration.
2. Add the exact artifact path and measured result.
3. Append a dated history entry.
4. Apply the status rules below.
5. Update the catalog row only when its status or current target changes.

### Create a new Fault Category Record

Create a record only when every gate passes:

1. **Artifact gate:** Persisted evidence demonstrates the failure; an interpretation or hypothesis alone does not.
2. **Category gate:** The candidate describes a reusable failure mode, not one failed test, exception message, model, checkpoint, or numeric result.
3. **Distinctness gate:** No existing record represents the same affected invariant and remediation target.
4. **Detection gate:** The record can state an observable signal that later experiments can evaluate consistently.
5. **Evidence gate:** At least one exact experiment configuration and measured example can populate the observed-configurations table.
6. **Impact gate:** The failure has a concrete correctness, regression, integration, recovery, structural, or process consequence.
7. **Resolution gate:** A measurable criterion can test the broader category without encoding only the original example.

Do not create a record when any gate fails. If distinctness remains ambiguous after comparing all records, make no catalog change and report the candidate records and unresolved distinction.

When every gate passes:

1. Allocate the next unused sequential `FCR-NNN`; never fill a historical gap or renumber records.
2. Create `fault-category-records/FCR-NNN-<canonical-fault-category-slug>.md` using the fault-category-record-schema.
3. Set status to `open` unless the experiment was explicitly registered as targeting this category before execution.
4. Add the linked catalog row and detail file atomically.
5. Confirm the ID, canonical wording, category, status, and current target match in both files.

## Apply Status Rules

Status describes evidence about the fault category, not whether one assertion currently passes.

### Keep `open`

Keep `open` when:

- an experiment provides another occurrence but did not target the category;
- the result is worse, unchanged, or incomparable;
- an intervention was attempted without a preregistered resolution criterion;
- evidence is insufficient for `mitigated`, `resolved`, or `not-reproducible`.

Append the occurrence and history without presenting repeated evidence as progress.

### Change to `targeted`

Change `open` or `reopened` to `targeted` only before execution, after recording:

- the experiment identifier;
- the intervention intended to address the category;
- the unchanged measurable resolution criterion;
- the evaluation scope, including configurations, checkpoints, seeds, and runs required by that criterion.

Starting or selecting an experiment is not mitigation.

### Change to `mitigated`

Change `targeted` to `mitigated` only when:

- the planned intervention was actually applied;
- comparable evidence shows improvement in the category’s detection signal;
- the full resolution criterion did not pass, or its required scope is incomplete;
- no material regression elsewhere invalidates the improvement.

Record the baseline, result, remaining gap, intervention, and artifact paths. Never use `mitigated` for an unmeasured qualitative impression.

### Change to `resolved`

Change `targeted` or `mitigated` to `resolved` only when every condition holds:

1. The resolution criterion existed before the validating run and was not weakened afterward.
2. The planned intervention was applied and is recorded under `Solution`.
3. Every metric, checkpoint, configuration, seed, and run required by the criterion completed successfully.
4. The result meets the full threshold, not merely an improvement over baseline.
5. The original detection signal is absent within the criterion’s declared scope.
6. Cumulative and regression results show no material displacement of the fault into another behavior.
7. Exact validation artifacts and measurements are recorded.

If the existing criterion does not define enough scope to support a category-level resolution claim, keep the record `mitigated`, strengthen the criterion prospectively, and validate it in a later experiment. Never retroactively strengthen, weaken, or reinterpret a criterion using the current result.

### Change to `reopened`

Change `resolved` to `reopened` only when all regression conditions hold:

1. A later completed experiment reproduces the same recurring failure mode and affected invariant.
2. The original detection signal reappears using an equivalent measurement.
3. The result violates the recorded resolution criterion within its declared scope, or disproves a category-wide resolution claim.
4. The evidence is not solely a different assertion, unrelated failure, missing artifact, harness error, or incomparable configuration.
5. The reproducing configuration and artifact evidence are appended to the record.

A severity increase on an already open or mitigated record is additional evidence, not `reopened`. A failure outside a deliberately narrow resolved scope is recorded as a new occurrence; reopen only if it contradicts the resolution claim.

### Change to `not-reproducible`

Change `open` to `not-reproducible` only when a controlled follow-up recreates the original harness, model, reasoning level, fixture, seed, checkpoint scope, and detection method but the fault does not recur.

Use `not-reproducible` for an unconfirmed observation, not for a fault improved by an intervention. An intervention that removes the fault must follow the targeted-to-resolved path.

## Record the Outcome

For every creation or update:

1. Preserve all prior evidence, unsuccessful interventions, and history.
2. Append observed configurations with experiment, checkpoint, harness revision, agent runtime, exact model, reasoning level, and measured evidence.
3. Record exact artifact-relative paths; do not cite only an observations summary.
4. Record the prior status, resulting status, experiment, decision, and reason in chronological history.
5. Update the catalog index and Fault Category Record together when status or targeting changes.
6. Keep API-equivalent estimates distinct from actual billed cost.
7. Never include credentials or secret material.

## Validation

Before completing:

- Every candidate has an explicit `create`, `update`, `reopen`, or `no change` decision.
- Every new record passes all seven creation gates.
- No new record duplicates an existing invariant and remediation target.
- Every status transition is allowed by the schema and satisfies every condition in its status section.
- Every `resolved` record meets its preregistered criterion across the declared scope with no material regression elsewhere.
- Every `reopened` record reproduces the same category and contradicts the recorded resolution claim.
- Index and detail IDs, canonical wording, category, status, and current target match.
- Every quantitative claim and occurrence points to persisted artifact evidence.
