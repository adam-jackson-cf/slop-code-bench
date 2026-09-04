# Terminal Handoff Runbook

## Objective

Hand a completed matrix's verified terminal artifacts to `experiment-observations` for analysis.

## Preconditions

- Every configured matrix member has reached its canonical terminal execution state.
- Every member retains a readable, repository-relative artifact path for its resolved configuration, manifest/provenance, run summary, checkpoint results, per-checkpoint evaluations, quality metrics, and any telemetry required for a claim.

## Procedure

1. Enumerate the configured members from the resolved matrix configuration and verify each member's canonical terminal execution state.
2. For every member, verify that each required artifact path is repository-relative, exists, and is readable:
   - resolved configuration;
   - manifest/provenance;
   - run summary;
   - checkpoint results;
   - one evaluation artifact for every configured checkpoint;
   - quality metrics; and
   - every telemetry artifact required to support a claim.
3. A manifest/provenance artifact MAY stand in for an artifact inventory only after verifying that it enumerates every required artifact above and that every enumerated path resolves to the corresponding readable artifact. Do not infer, omit, or substitute an artifact path from the manifest.
4. Verify each member used the equivalent-run controls: fixture, seed, agent harness and runner revision, environment, prompt, reasoning level, checkpoint sequence, assessment policy, model identity, measurement definitions, and requested experimental variable.
5. Do not interpret completion quality, classify faults, compare behavior, or compose user-facing results.

## Handoff

Provide `experiment-observations` a terminal matrix handoff payload containing:

- the equivalent-run controls: fixture, seed, agent harness and runner revision, environment, prompt, reasoning level, checkpoint sequence, assessment policy, model identity, measurement definitions, and requested experimental variable;
- for every configured member, its experiment identifier and canonical terminal execution state;
- for every member, repository-relative paths to its resolved configuration, manifest/provenance, run summary, checkpoint results, quality metrics, and telemetry required for claims; and
- for every member, a checkpoint-keyed list of repository-relative paths to its per-checkpoint evaluation artifacts.

If a required member is not terminal, a required artifact is unavailable, or a manifest/provenance artifact does not enumerate and resolve every required artifact, return that execution fact to the caller and do not hand off the matrix as complete.
