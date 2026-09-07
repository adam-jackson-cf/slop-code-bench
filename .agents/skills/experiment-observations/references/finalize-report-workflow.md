# Create and finalize the observations report

1. Create a new, never-overwritten full report at `experiment_analysis/<ddMMyy>-exp-observations-<NNN>.md`. Use the current local date, find only valid files matching that date's pattern, select one greater than the highest three-digit sequence (starting at `001`), and recalculate if the selected path already exists.
2. Make the full report evidence-first and traceable. Preserve the existing narrative and include: objective and equivalent-run cohort; terminal artifact paths and validation decisions; Completion Summary; Scoring Provenance; recalculated completed-run metrics; Scoring Quality; Quality Trajectories; checkpoint-level evidence; catalog-reconciled observed fault entries; limitations; Measured Interpretation; and Key Takeaways. Include the returned canonical ID, exact fault type, category, status, affected models/checkpoints, concise measured evidence, repository-relative record path, and changed-record IDs for each reconciled entry.
3. In `Scoring Provenance`, identify the published generation, eligibility, formula ID, canonical producer statuses, and sanitized evaluator identity. Show evaluator implementation, cache tag, and executable SHA-256 only. Never expose an absolute evaluator executable path. Treat `result.json` and `experiment_summary.txt` as projections rather than scoring authority.
4. Structure `Scoring Quality` as two levels for each configured problem: `Overall performance — <problem>` followed by `Quality issue breakdown — <problem>`. Never mix benchmark aggregates and problem-level values in one table. In overall performance, display `Final score` as points out of 100, not as a percentage. Display `Requirements passed` and `Quality multiplier` as percentages, and `Quality deduction` as signed points. Calculate them only from the verified problem values: `Requirements passed = 100 × Correctness`, `Quality multiplier = 100 × (70% + 30% × Inertia)`, and `Quality deduction = Score − (100 × Correctness)`.
5. Present diagnostic components as issue rates where lower is better. Calculate each `Issue rate ↓` as `100 × (1 − canonical component)` and each `Weighted penalty` as the issue rate multiplied by its canonical weight. Use these exact mappings and weights: `Production concision` from the inverse of Production concision (15%); `Structural complexity` from the inverse of Structural quality (15%); `Architecture cycles` from the inverse of Acyclic architecture (20%); `Repeated rework` from the inverse of Rework stability (30%); and `Regression exposure` from the inverse of Regression resistance (20%). Weighted penalties sum to `Quality risk = 100 × (1 − Inertia)`. Use consistent precision within a table. Render any unavailable outcome, issue rate, or weighted penalty as `Unavailable` when its canonical producer is blocked; never translate unavailable evidence to zero or derive a dependent value from it. Keep canonical producer statuses in `Scoring Provenance`, not in the performance tables.
6. In `Quality Trajectories` and `Measured Interpretation`, distinguish measured evidence from interpretation and preserve the issue-rate direction: lower is better. Do not repeat the component explanations from `Scoring Quality`.
   - `8/8` means executed checkpoints, not checkpoints passing every required case.
7. Do not include improvement recommendations or model-selection advice.
8. Return a concise observations view to the user using exactly the output template below:

   - `- Checkpoints: <each is an equivalent assessment checkpoint, and all listed runs reached terminal state>.`
   - `- Mean pass rate: <the average across all required current or accumulated regression cases at equivalent checkpoints>.`
   - `- 100% requirement: <a checkpoint appears as complete only when every required current or accumulated regression case passed>.`
   - `- One-failure rule: <one failed current or accumulated regression case keeps a checkpoint below 100%, even when the mean pass rate is high>.`
   - `- Units: <partial results are individual passed cases; complete results are checkpoints with 100% pass rate>.`

   `Completion Summary`

   | Model | Policy | Executed checkpoints | Tests | Final score | Cost | Duration | Steps |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | `<model>` | `<assessment policy>` | `<executed/configured>` | `<passed/total>` | `<verified benchmark score / 100 or Unavailable>` | `<cost>` | `<duration>` | `<steps>` |

   | Model | Mean pass rate across all checkpoints | Checkpoints with 100% pass rate |
   | --- | --- | --- |
   | `<model>` | `<recalculated percentage>` | `<completed checkpoint count, e.g. 0 of 8>` |

   `Scoring Quality`

   `Overall performance — <problem>`
   | Model | Outcome | Result | Meaning |
   | --- | --- | --- | --- |
   | `<model>` | `Final score` | `<verified problem score / 100 or Unavailable>` | `Requirements performance after the quality adjustment.` |
   | `<model>` | `Requirements passed` | `<verified percentage or Unavailable>` | `Mean required-case pass rate across the problem's configured checkpoints.` |
   | `<model>` | `Quality multiplier` | `<verified percentage or Unavailable>` | `Multiplier applied to Requirements passed: 70% + 30% × Inertia.` |
   | `<model>` | `Quality deduction` | `<signed points or Unavailable>` | `Points removed from Requirements passed by the Quality multiplier.` |
   `Quality issue breakdown — <problem>`

   | Model | Area | Issue rate ↓ | Weight | Weighted penalty | What was detected |
   | --- | --- | --- | --- | --- | --- |
   | `<model>` | `Production concision` | `<verified percentage or Unavailable>` | `15%` | `<verified points or Unavailable>` | `Production lines flagged by the selected simplification rules or clone detection.` |
   | `<model>` | `Structural complexity` | `<verified percentage or Unavailable>` | `15%` | `<verified points or Unavailable>` | `Complexity-weighted production functions and methods above cyclomatic complexity 10.` |
   | `<model>` | `Architecture cycles` | `<verified percentage or Unavailable>` | `20%` | `<verified points or Unavailable>` | `Production dependency-graph mass inside dependency cycles.` |
   | `<model>` | `Repeated rework` | `<verified percentage or Unavailable>` | `30%` | `<verified points or Unavailable>` | `Changed production lines attributed to symbols changed in an earlier checkpoint.` |
   | `<model>` | `Regression exposure` | `<verified percentage or Unavailable>` | `20%` | `<verified points or Unavailable>` | `Changed production symbols attributed to failing canonical regression cases.` |

   `Key Takeaways`

   | Model | Published generation | Eligibility | Formula ID | Evaluator identity |
   | --- | --- | --- | --- | --- |
   | `<model>` | `<generation ID>` | `<canonical eligibility>` | `<formula ID>` | `<implementation; cache tag; executable SHA-256>` |

   `Observed fault types`

   - `<canonical ID> — <exact fault type> (<category>; <status>): <affected models/checkpoints>; <concise measured evidence>; [record](<repository-relative record path>)`

   `Full report`

   - `[<ddMMyy>-exp-observations-<NNN>.md](experiment_analysis/<ddMMyy>-exp-observations-<NNN>.md)`

9. Populate every placeholder with validated Step 1 data and Step 2 reconciliation results. Render both `Scoring Quality` tables once per configured problem, with rows for every included model. If there are no reconciled faults, write `- None observed.` under `Observed fault types`. Do not add any other section, recommendation, model-selection advice, or prose to the concise response.
