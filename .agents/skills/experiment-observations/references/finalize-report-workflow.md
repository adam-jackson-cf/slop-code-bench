# Create and finalize the observations report

1. Create a new, never-overwritten full report at `experiment_analysis/<ddMMyy>-exp-observations-<NNN>.md`. Use the current local date, find only valid files matching that date's pattern, select one greater than the highest three-digit sequence (starting at `001`), and recalculate if the selected path already exists.
2. Make the full report evidence-first and traceable. Preserve the existing narrative and include: objective and equivalent-run cohort; terminal artifact paths and validation decisions; Completion Summary; Scoring Provenance; recalculated completed-run metrics; Scoring Quality; Quality Trajectories; checkpoint-level evidence; catalog-reconciled observed fault entries; limitations; Measured Interpretation; and Key Takeaways. Include the returned canonical ID, exact fault type, category, status, affected models/checkpoints, concise measured evidence, repository-relative record path, and changed-record IDs for each reconciled entry.
3. In `Scoring Provenance`, identify the published generation, eligibility, formula ID, canonical producer statuses, and sanitized evaluator identity. Show evaluator implementation, cache tag, and executable SHA-256 only. Never expose an absolute evaluator executable path. Treat `result.json` and `experiment_summary.txt` as projections rather than scoring authority.
4. In `Scoring Quality`, preserve these exact labels: `Production concision`, `Structural quality`, `Acyclic architecture`, `Rework stability`, and `Regression resistance`. Render `Unavailable` whenever the canonical producer status blocks a component. Do not replace unavailable evidence with zero or one or derive inertia or score from unavailable components.
5. In `Quality Trajectories` and `Measured Interpretation`, distinguish measured evidence from interpretation and apply these definitions:
   - `8/8` means executed checkpoints, not checkpoints passing every required case.
   - `Production concision` measures unflagged production LOC.
   - `Structural quality` reports structural erosion.
   - `Acyclic architecture` may remain high while some cyclic mass exists.
   - `Rework stability` is lineage-based repeated-change evidence.
   - `Regression resistance` is attributed regression breadth, not generic pass rate.
6. Do not include improvement recommendations or model-selection advice.
7. Return a concise observations view to the user using exactly the output template below:

   - `- Checkpoints: <each is an equivalent assessment checkpoint, and all listed runs reached terminal state>.`
   - `- Mean pass rate: <the average across all required current or accumulated regression cases at equivalent checkpoints>.`
   - `- 100% requirement: <a checkpoint appears as complete only when every required current or accumulated regression case passed>.`
   - `- One-failure rule: <one failed current or accumulated regression case keeps a checkpoint below 100%, even when the mean pass rate is high>.`
   - `- Units: <partial results are individual passed cases; complete results are checkpoints with 100% pass rate>.`

   `Completion Summary`

   | Model | Policy | Executed checkpoints | Tests | Strict score | Cost | Duration | Steps |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | `<model>` | `<assessment policy>` | `<executed/configured>` | `<passed/total>` | `<verified score or Unavailable>` | `<cost>` | `<duration>` | `<steps>` |

   | Model | Mean pass rate across all checkpoints | Checkpoints with 100% pass rate |
   | --- | --- | --- |
   | `<model>` | `<recalculated percentage>` | `<completed checkpoint count, e.g. 0 of 8>` |

   `Scoring Quality`

   | Model | Scope | Quality component | Value | Evidence status |
   | --- | --- | --- | --- | --- |
   | `<model>` | `Benchmark` | `Correctness` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `Benchmark` | `Inertia` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Score` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Production concision` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Structural quality` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Acyclic architecture` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Rework stability` | `<verified value or Unavailable>` | `<canonical status>` |
   | `<model>` | `<problem>` | `Regression resistance` | `<verified value or Unavailable>` | `<canonical status>` |

   `Key Takeaways`

   | Model | Published generation | Eligibility | Formula ID | Evaluator identity |
   | --- | --- | --- | --- | --- |
   | `<model>` | `<generation ID>` | `<canonical eligibility>` | `<formula ID>` | `<implementation; cache tag; executable SHA-256>` |

   `Observed fault types`

   - `<canonical ID> — <exact fault type> (<category>; <status>): <affected models/checkpoints>; <concise measured evidence>; [record](<repository-relative record path>)`

   `Full report`

   - `[<ddMMyy>-exp-observations-<NNN>.md](experiment_analysis/<ddMMyy>-exp-observations-<NNN>.md)`

8. Populate every placeholder with validated Step 1 data and Step 2 reconciliation results. Repeat table rows for every included model and configured problem. If there are no reconciled faults, write `- None observed.` under `Observed fault types`. Do not add any other section, recommendation, model-selection advice, or prose to the concise response.
