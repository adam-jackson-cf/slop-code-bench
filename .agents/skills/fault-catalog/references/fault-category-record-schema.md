# Fault Category Record Schema

## Objective

Define the canonical catalog index, Fault Category Record shape, statuses, and integrity rules used by every maintenance action.

## Canonical paths

- `experiment_analysis/fault-catalog.md` is the high-level index and status view.
- `experiment_analysis/fault-category-records/` contains one Fault Category Record per reusable fault category.
- Name records `FCR-NNN-<canonical-fault-category-slug>.md`.
- Never create a parallel catalog or reuse an identifier.

## Catalog index schema

Keep the catalog limited to its purpose statement and this table:

```markdown
| ID | Fault type | Category | Status | First observed | Current target |
|---|---|---|---|---|---|
| [`FCR-NNN`](fault-category-records/FCR-NNN-fault-category.md) | Canonical fault category | Category | `status` | Experiment | Experiment or — |
```

The linked ID, canonical fault-category wording, category, status, and target must match the Fault Category Record.

## Fault Category Record schema

Each record contains:

```markdown
# FCR-NNN — Canonical fault category

- **Category:** Behavioral | Integration | Recovery | Structural | Process
- **Status:** `open`
- **Description:** Recurring failure mode.
- **Detection signal:** Observable experiment pattern.
- **Example evidence:** One concrete experiment, checkpoint, model, and measurement.
- **Observed configurations:**

  | Experiment | Checkpoint | Harness | Agent runtime | Model | Reasoning | Evidence |
  |---|---|---|---|---|---|---|
  | Experiment identifier | Checkpoint or range | Harness and pinned revision | Agent runtime and version | Exact runtime model identifier | Reasoning level | Concise measured result. |

- **Impact:** Cumulative-development consequence.
- **Working hypothesis:** Suspected cause, explicitly identified as a hypothesis.
- **Resolution criterion:** Measurable broader-behavior condition defined before targeting.
- **Target experiment:** Experiment identifier or `—`.
- **Solution:** Intervention or `—`.
- **Validation evidence:** Artifact and measurement or `—`.
- **History:**
  - YYYY-MM-DD — Event and experiment identifier.
```

An observed-configuration row proves that configuration displayed the fault. Absence does not prove that another configuration is immune. Append every evidenced occurrence with the harness revision, agent version, exact model, and reasoning level.

## Status lifecycle

| Status | Meaning |
|---|---|
| `open` | Observed and evidenced; no intervention selected. |
| `targeted` | An upcoming or active experiment explicitly targets the fault. |
| `mitigated` | An intervention improved the fault without satisfying the full criterion. |
| `resolved` | The predefined criterion passed and the solution is recorded. |
| `reopened` | A later experiment reproduced a resolved fault. |
| `not-reproducible` | A controlled follow-up could not reproduce the observation. |

Allowed transitions:

```text
open → targeted → mitigated → resolved
            └──────────────→ resolved
resolved → reopened → targeted
open → not-reproducible
```

A lower failure count alone is not resolution. Resolution requires the predefined criterion and no material regression elsewhere.

## Integrity rules

- Preserve exact Fault Category Record IDs and canonical fault-category wording.
- Keep the catalog row and Fault Category Record synchronized in the same change.
- Never delete records, historical evidence, unsuccessful interventions, or resolved categories.
- Allocate new IDs sequentially and never renumber existing records.
- Keep procedural guidance in this skill, not in the catalog or Fault Category Records.
- Keep quantitative claims traceable to persisted artifacts.
- Never include credentials or secret material.
- Distinguish API-equivalent estimates from actual billed cost.
