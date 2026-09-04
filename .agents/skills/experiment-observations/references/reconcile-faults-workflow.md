# Reconcile observed faults

1. Send only the candidate failure evidence prepared in Step 1 to `fault-catalog` and use its reconciliation action before any fault name appears in an observations artifact or concise response.
2. Treat `fault-catalog` as the exclusive authority for canonical fault IDs, exact fault-type wording, categories, statuses, and catalog mutations. Do not create, rename, deduplicate, transition, or otherwise mutate catalog records directly.
3. Require a reconciliation result for every observed fault entry with: canonical ID, exact fault type, category, status, affected models and checkpoints, concise measured evidence, a relative record link, and changed-record IDs. Retain the returned wording verbatim; do not coin aliases or summarize it into a new fault label.
4. If candidate evidence cannot be reconciled, omit it from `Observed fault types` and identify the unresolved evidence only in the full report's limitations with its artifact-relative path. Never present an unreconciled candidate as a canonical fault.
5. Carry the returned entries and changed-record IDs into Step 3. The observations skill coordinates this evidence handoff; `fault-catalog` remains the owner of every catalog mutation.
