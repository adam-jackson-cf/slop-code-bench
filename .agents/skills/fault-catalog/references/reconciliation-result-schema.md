# Reconciliation Result Schema

## Purpose

Use this portable result only after each candidate from a completed experiment has been reconciled through the [Update Fault Status runbook](update-fault-status-runbook.md). It is the fault-catalog handoff to observations summaries. It does not summarize the experiment or control experiment lifecycle.

## Result Contract

Return one entry in `reconciled_faults` for each failure mode that the completed [Update Fault Status runbook](update-fault-status-runbook.md) reconciles to an existing or newly created Fault Category Record, including a `no change` decision. Every entry MUST contain these fields:

| Field | Required value |
| --- | --- |
| `canonical_id` | The non-null canonical Fault Category Record ID, such as `FCR-012`. |
| `exact_fault_type` | The exact canonical fault type wording from the linked Fault Category Record. Do not abbreviate, paraphrase, or create an alternate label. |
| `category` | The canonical category from the linked Fault Category Record. |
| `status` | The resulting canonical record status after reconciliation. |
| `affected_models_checkpoints` | A list of exact model identifiers paired with the completed checkpoints evidenced by this reconciliation. |
| `concise_measured_evidence` | A short, quantitative or otherwise directly measured statement backed by persisted artifacts; include the relevant comparison scope when necessary. |
| `relative_record_link` | A non-null repository-relative path string to the Fault Category Record, such as `experiment_analysis/fault-category-records/FCR-012-example.md`; do not use Markdown link syntax. |
| `changed_record_ids` | A list of every Fault Category Record ID created or changed by this reconciliation; use `[]` for no catalog change. |

Candidates for which the runbook reaches no catalog change because distinctness remains unresolved MUST NOT appear in `reconciled_faults`. If they must be retained in the portable result, place them only in the optional `unresolved_candidates` collection. Each unresolved candidate MUST include:

| Field | Required value |
| --- | --- |
| `candidate_evidence` | A concise, directly measured description of the non-canonical candidate and its comparison scope. It is evidence, not a fault type. |
| `relative_artifact_links` | One or more repository-relative Markdown links to persisted artifacts supporting the candidate. |
| `reason` | The unresolved distinctness decision and the candidate Fault Category Records compared. |

## Portable Form

```yaml
reconciled_faults:
  - canonical_id: FCR-012
    exact_fault_type: "Exact canonical wording from the Fault Category Record"
    category: "Canonical category"
    status: open
    affected_models_checkpoints:
      - model: "exact-model-identifier"
        checkpoints: ["checkpoint-name"]
    concise_measured_evidence: "Measured result with artifact-backed scope."
    relative_record_link: "experiment_analysis/fault-category-records/FCR-012-example.md"
    changed_record_ids: ["FCR-012"]

unresolved_candidates:
  - candidate_evidence: "Measured non-canonical candidate with artifact-backed comparison scope."
    relative_artifact_links:
      - "[experiment artifact](experiment_analysis/example/artifact.json)"
    reason: "Distinctness remains unresolved after comparison with FCR-012 and FCR-019; no catalog change."
```

## Consumer Rules

- Observations summaries MUST consume only `reconciled_faults` and use `exact_fault_type`; they MUST NOT coin alternate labels or render `unresolved_candidates` as fault types.
- Consumers can omit unresolved candidates deterministically by ignoring the optional `unresolved_candidates` collection.
- The linked record remains the authority for canonical ID, wording, category, and status.
- Catalog mutations remain exclusively governed by the [Update Fault Status runbook](update-fault-status-runbook.md); this schema neither authorizes mutation nor replaces its decisions, evidence rules, or status-transition rules.
