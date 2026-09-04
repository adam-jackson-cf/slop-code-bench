# Metrics Reference

Per-checkpoint metrics in `checkpoint_results.jsonl`, run-level summary in `result.json`.

---

## Checkpoint vs Problem Aggregation

`result.json` reports most metrics at two levels:

**Checkpoint-level**: one value per checkpoint, stats across all checkpoints in the run.

```
[c1_p1, c2_p1, c1_p2, c2_p2, c3_p2, ...]  →  MetricStats
```

**Problem-level**: aggregate within each problem first (sum or mean), then stats across problems.

```
P1 = sum(c1_p1, c2_p1),  P2 = sum(c1_p2, c2_p2, c3_p2)  →  MetricStats
```

| Category | Problem-level aggregation |
|----------|--------------------------|
| Cost, time, steps, tokens | **Sum** within problem |
| Pass rates | **Mean** within problem |
| Quality, deltas, composites | Checkpoint-level only |

**Use checkpoint-level** for per-step behavior: typical cost per checkpoint, quality at a point in time, whether quality degrades as checkpoints accumulate.

**Use problem-level** for end-to-end performance: total cost to solve a problem, overall solvability, comparing model efficiency across runs.

### Comparing Runs

| Question | Metric |
|----------|--------|
| Solves more? | `pct_problems_solved`, `pct_checkpoints_solved` |
| Meets core spec? | `pct_checkpoints_core_solved`, `pass_rates.checkpoint.core` |
| Breaks prior work? | `pass_rates.checkpoint.regression` |
| Cleaner code? | `ratios.lint.mean`, `verbosity.mean` |
| Quality degrades? | `delta.loc`, `delta.verbosity`, `delta.churn_ratio`, `erosion.mean` |
| Cheaper end-to-end? | `costs.problem.mean`, `costs.total` |
| Fewer steps? | `steps.checkpoint.mean` |

### Pass Rate Variants

- **`pass_rate`** — all tests including regression. Strictest: solved this checkpoint *and* didn't break prior ones.
- **`checkpoint_pass_rate`** — excludes regression. Did the agent solve the new requirements?
- **`core_pass_rate`** — core tests only. Did the agent meet the minimum spec?

The gap between `pct_checkpoints_solved` and `pct_checkpoints_iso_solved` reveals how often an agent solves new requirements but breaks old ones.

---

## checkpoint_results.jsonl

One JSON object per line per checkpoint. **A missing row means the agent errored or timed out before reaching that checkpoint** — the directory was never created, so no metrics were emitted. When a row is present but `state` is `"error"`, the agent attempted the checkpoint but failed during execution; evaluation and quality metrics may be partially or entirely absent. Only rows with `state == "ran"` have a complete metric set.

### Identification

| Key | Description |
|-----|-------------|
| `checkpoint` | Checkpoint name (e.g., `"checkpoint_1"`) |
| `problem` | Problem name |
| `path` | Relative path to checkpoint directory |
| `idx` | Order index within problem |
| `version` | Problem version |
| `state` | `"ran"`, `"skipped"`, or `"error"` |
| `is_first`, `is_last` | Position flags |

### Inference

From `inference_result.json`.

| Key | Description |
|-----|-------------|
| `started`, `ended` | ISO timestamps |
| `elapsed` | Wall-clock seconds (`ended - started`) |
| `cost` | API cost in USD |
| `steps` | Agent steps (tool calls / turns) |
| `input`, `output` | Token counts |
| `cache_read`, `cache_write` | Prompt cache tokens |
| `reasoning` | Extended thinking tokens |

### Evaluation

From `evaluation.json`. Tests grouped by pytest markers:
- **Core** (unmarked) — must pass to solve the checkpoint
- **Functionality** (`@pytest.mark.functionality`) — optional feature coverage
- **Error** (`@pytest.mark.error`) — error handling
- **Regression** — prior checkpoint tests re-run

| Key | Calculation |
|-----|-------------|
| `total_tests`, `passed_tests` | Counts across all groups |
| `pass_rate` | `passed_tests / total_tests` |
| `checkpoint_pass_rate` | `(passed - regression_passed) / (total - regression_total)` |
| `core_pass_rate` | `core_passed / core_total` |
| `{core,functionality,error,regression}_total` | Per-group test count |
| `{core,functionality,error,regression}_passed` | Per-group pass count |
| `duration` | Pytest execution seconds |

### Code Size

From `overall_quality.json` and file/symbol iteration.

| Key | Description |
|-----|-------------|
| `loc` | Source lines (excludes comments and blanks) |
| `total_lines` | All lines including comments and blanks |
| `files` | Total measured files |
| `lines_added`, `lines_removed` | Diff from prior checkpoint |
| `single_comments` | Single-line comment count |

### Symbols & Structure

| Key | Description |
|-----|-------------|
| `symbols_total` | Functions + methods + classes + variables + type aliases |
| `functions`, `methods`, `classes` | Counts by type |
| `statements` | Total statements across all symbols |
| `mean_func_loc`, `lines_per_symbol` | Mean LOC per function/method |

### Cyclomatic Complexity

Per function/method, radon scale.

| Key | Description |
|-----|-------------|
| `cc_max`, `cc_mean`, `cc_std` | Max, mean, stddev across functions |
| `cc_high_count` | Functions with CC > 10 |
| `cc_extreme_count` | Functions with CC > 30 |
| `high_cc_mean` | Mean CC among high-CC functions only |
| `cc_normalized` | Normalized CC score |
| `cc_concentration` | Gini of CC distribution (0=uniform, 1=concentrated) |

### Linting

| Key | Description |
|-----|-------------|
| `lint_errors` | Total lint violations |
| `lint_fixable` | Auto-fixable violations |
| `lint_per_loc` | `lint_errors / loc` |

### `scb-check` & Waste

| Key | Description |
|-----|-------------|
| `cloned_sloc_lines` | Duplicated SLOC lines reported by `scb-check` |
| `cloned_pct` | `scb-check` clone LOC / total LOC |
| `verbosity_flagged_sloc_lines` | Verbosity-flagged SLOC reported by `scb-check` |
| `verbosity_flagged_pct` | `scb-check` flagged LOC / total LOC |
| `single_use_functions` | Functions called only once |
| `trivial_wrappers` | Functions that just delegate to another |
| `unused_variables` | Variables assigned but never read |

### Rubric (LLM Judge)

From `rubric.jsonl`. Each record is a violation flagged by an LLM judge.

| Key | Description |
|-----|-------------|
| `rubric_total_flags` | Total violations |
| `rubric_carried_over` | Violations carried from prior checkpoint |
| `rubric_verbosity_flags`, `rubric_erosion_flags` | By violation type |
| `rubric_per_loc` | `rubric_total_flags / loc` |

### Dependency Graph (Optional, Python only)

| Key | Description |
|-----|-------------|
| `graph_cyclic_dependency_mass` | Edge weight in SCCs / total edge weight. Higher = more circular deps. |
| `graph_propagation_cost` | Average reachability in transitive closure. Higher = more ripple risk. |
| `graph_dependency_entropy` | Normalized Shannon entropy. Lower = deps concentrated on few modules. |

### Mass Metrics

Size-weighted CC mass uses true symbol SLOC:

```text
mass.cc = sum(complexity * sqrt(symbol_sloc))
```

| Key | Description |
|-----|-------------|
| `mass.cc` | Total CC mass across functions and methods |
| `mass.high_cc_pct` | Percent of `mass.cc` contributed by functions/methods with `CC > 10` |

### Delta Metrics

Present for all checkpoints after the first.

**Percentage deltas**: `((current - prior) / prior) * 100`. Returns `inf` if prior=0 and current>0.

| Key | Description |
|-----|-------------|
| `delta.loc` | % change in LOC |
| `delta.verbosity` | % change in the `scb-check` verbosity score |
| `delta.churn_ratio` | `(lines_added + lines_removed) / prior_total_lines` |

---

## result.json

Run-level summary. All `MetricStats` fields contain `{mean, stddev, min, max, median, count}` (stddev is null if < 2 samples).

### Run Metadata

| Key | Description |
|-----|-------------|
| `model`, `agent_type`, `agent_version` | Model and agent identification |
| `thinking` | `"none"`, `"low"`, `"medium"`, `"high"` |
| `prompt` | Prompt template stem |
| `num_problems`, `num_checkpoints` | Run scope |

### Costs, Time, Steps

| Key | Type | Description |
|-----|------|-------------|
| `costs.checkpoint`, `costs.problem` | MetricStats | Per-checkpoint / per-problem cost (USD) |
| `costs.total` | float | Total run cost |
| `time.checkpoint`, `time.problem` | MetricStats | Elapsed seconds |
| `steps.checkpoint`, `steps.problem` | MetricStats | Agent step counts |

### Tokens

| Key | Description |
|-----|-------------|
| `tokens.{input,output,cache_read,cache_write,reasoning}` | Totals across the run |
| `tokens.checkpoint.*`, `tokens.problem.*` | Mean per checkpoint / per problem (same five fields) |

### Solve Rates

A checkpoint is "solved" at `pass_rate == 1.0`.

| Key | Description |
|-----|-------------|
| `checkpoints_solved` | Count with `pass_rate == 1.0` |
| `checkpoints_iso_solved` | Count with `checkpoint_pass_rate == 1.0` (ignoring regression) |
| `checkpoints_core_solved` | Count with `core_pass_rate == 1.0` |
| `problem_solved` | Problems where *all* checkpoints pass at 1.0 |
| `problem_partial` | Problems where *at least one* checkpoint passes at 1.0 |
| `pct_checkpoints_solved`, `pct_checkpoints_iso_solved`, `pct_checkpoints_core_solved` | Percentages of above |
| `pct_problems_solved`, `pct_problems_partial` | Percentages of above |

### Pass Rates

Checkpoints with zero tests for a type are excluded from that type's average.

| Key | Description |
|-----|-------------|
| `pass_rates.checkpoint.{core,total,error,functionality,regression}` | Mean rate across checkpoints |
| `pass_rates.problem.{...}` | Mean per-problem first, then across problems |

### Quality

| Key | Type | Description |
|-----|------|-------------|
| `cc.high_count`, `cc.high_mean`, `cc.max` | MetricStats | CC stats across checkpoints |
| `ratios.rubric`, `ratios.lint` | MetricStats | `metric / loc` per checkpoint |

### Canonical Checkpoint Scoring

`result.json` and checkpoint summaries are descriptive metrics, not score
authority. Canonical scores are emitted only as a verified published generation
under `measurement_analysis/`.

#### Components and formulas

For a configured problem with `K_p` checkpoints, `C_p,k` is the canonical
`passed / total` correctness rate for checkpoint `k`. `V`, `E`, and `H` are
the means of checkpoint `verbosity`, `erosion`, and `architecture`; `R` and
`G` are the means of adjacent-transition `rework` and `regression`.

```text
C_p=sum(C_p,k)/K_p
I_p=.15V_p+.15E_p+.20H_p+.30R_p+.20G_p
S_p=100*C_p*(.70+.30*I_p)
S_b=sum(S_p)/P;C_b=sum(C_p)/P;I_b=sum(I_p)/P
```

The component weights are `verbosity=0.15`, `erosion=0.15`,
`architecture=0.20`, `rework=0.30`, and `regression=0.20`. All component
values are favorable finite values in `[0, 1]`: higher is better. These
canonical fields are not the similarly named descriptive values in
`result.json`. Formula arithmetic uses decimal context precision `50` and
`ROUND_HALF_EVEN`; emitted component values have `0.000000000001` places and
scores have `0.000001` places.

Each configured problem has at least two checkpoints. Checkpoint component
evidence covers every configured checkpoint in configured order; `rework` and
`regression` cover exactly its adjacent transitions. Missing configured problem
scores contribute zero to `S_b`, `C_b`, and `I_b`. A produced checkpoint must
have a finite non-negative `cost`; otherwise
`cost_per_configured_checkpoint` is `null`. Unproduced checkpoints contribute
zero cost.

#### Published artifacts and eligibility

A published generation is immutable at:

```text
measurement_analysis/generations/<generation_id>/
├── <evidence-indexed sidecars>
├── evidence_index.json
├── producer_status.json
├── eligibility.json
├── problems/<SHA256(UTF-8(exact problem name))>/problem_score.json  # eligible only
├── benchmark_score.json                # eligible only
├── checkpoint_report_additions.jsonl   # eligible only
├── manifest.json
└── READY
```

`current.json` is the canonical JSON object `{"generation_id":"<generation_id>"}`
and is the only current-generation pointer. `evidence_index.json` contains
ordered `path`, `kind`, `byte_length`, `sha256`, `producer`, and `status`
entries. `score_evidence.json` contains `problems` and `benchmark`; each problem
input contains `problem_id`, `checkpoint_ids`, `checkpoint_correctness`,
`verbosity`, `erosion`, `architecture`, `rework`, and `regression`, while
`benchmark` contains `configured_problem_ids`,
`configured_checkpoint_counts`, `costs`, and `run_identity`. `manifest.json`
contains `kind` (`"benchmark_score_generation"`), `schema_id`, `entries`,
`eligibility`, `publication_state`, `benchmark`, `ranking_position`, and
`report_additions`. The generation directory name is the SHA-256 of the final
canonical `manifest.json` bytes; the manifest does not contain a
self-referential generation ID. `benchmark_score.json` contains `problems`,
`benchmark_score`, `correctness`, `inertia`,
`cost_per_configured_checkpoint`, and `run_identity`; each problem score
contains `problem_id`, `configured_checkpoints`, `checkpoint_correctness`,
`components`, and `score`. `components` uses the canonical field names
`correctness`, `verbosity`, `erosion`, `architecture`, `rework`, `regression`,
and `inertia`.

Eligibility is `eligible=true` with no `reasons`, or `eligible=false` with
deduplicated ASCII-sorted `reasons`. The only reason values are
`canonical_artifact_invalid`, `canonical_provenance_unavailable`,
`canonical_test_denominator_zero`, `configured_problem_too_short`,
`coverage_parity_failed`, `coverage_parity_unavailable`,
`measurement_environment_mismatch`, `production_language_unsupported`,
`production_source_loc_zero`, `production_symbol_evidence_invalid`,
`score_evidence_invalid`, and `score_formula_invalid`. Input ineligibility
publishes an immutable scoreless generation with `eligibility.json`,
`producer_status.json`, `manifest.json`, and `READY`, then atomically replaces
`current.json`. Execution failure publishes no generation and leaves the prior
pointer unchanged.

Publication writes canonical, hash-indexed evidence into staging, verifies the
score, writes `READY`, atomically renames the completed generation, then
atomically replaces `current.json`. A failure cleans temporary staging and
pointer files; before pointer replacement, the prior current generation remains
current.

#### Consumer behavior

Consumers load only `current.json` through full verification: canonical pointer
bytes, `READY`, `manifest` kind, `generation_id`, `schema_id`,
`publication_state == "published"`, eligible `eligibility`, evidence hashes and
inventory, per-problem scores, and `benchmark_score.json` must all agree.
Invalid or unavailable generations are omitted from summaries, exports, and
rankings rather than projected from `result.json`. Dashboard and export
projections use `benchmark_score`, `correctness`, `inertia`,
`cost_per_configured_checkpoint`, `run_identity`, problem `score`, and the
canonical component fields. Ranking is
`benchmark_score:desc`, `correctness:desc`, `inertia:desc`,
`cost:nulls_last_asc`, `run_identity:asc`.
