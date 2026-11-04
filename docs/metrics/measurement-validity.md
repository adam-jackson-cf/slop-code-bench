---
version: 1.0
last_updated: 2026-10-03
---

# Measurement Validity

This page states what each SlopCodeBench measurement is allowed to claim, which
outcomes define those claims, and which evidence supports them. Use it before
interpreting a score, comparing runs, or changing a metric.

## Claims

| Claim | Meaning | Required evidence |
|-------|---------|-------------------|
| Correctness | The submission passes the checkpoint's full test suite, including hidden tests. | Strict `all-cases` evaluation. |
| Descriptive quality | The code has measured properties (verbosity, erosion, architecture cycles, rework, regression breadth). | Deterministic static and lineage measurement. |
| Predictive quality | A quality measurement at checkpoint N forecasts outcomes at checkpoint N+1. | Held-out validation against a correctness baseline; see [Validation status](#validation-status). |
| Causal inertia | Inherited code structure changes how hard the next change is. | Controlled continuations from matched starting implementations. |

A measurement may be reported only with the claim its evidence supports.
Quality components are descriptive unless the validation status below records
predictive or causal support.

## Outcomes

| Outcome | Definition | Source |
|---------|------------|--------|
| Checkpoint solved | Every evaluated test passes (`all-cases`). | `checkpoint_results.jsonl` `strict_pass_rate == 1.0` |
| New-requirement pass rate | Pass rate over tests introduced at this checkpoint. | `isolated_pass_rate` |
| Regression retained | Prior-checkpoint test passed at N-1 and passes at N. | `regression_retained` |
| Regression broken | Prior-checkpoint test passed at N-1 and fails at N. | `regression_broken` |
| Regression repaired | Prior-checkpoint test failed at N-1 and passes at N. | `regression_repaired` |
| Regression still failing | Prior-checkpoint test failed at N-1 and fails at N. | `regression_still_failing` |
| Effort | Cost, steps, tokens, and duration for the checkpoint, including failed and errored checkpoints. | `checkpoint_results.jsonl` |

Test identity is the pair (origin checkpoint, test name). A failing regression
test is inherited when it was already failing at the previous checkpoint and
newly broken when it passed there. Only newly broken tests describe damage done
by the change under evaluation.

## Predictor availability

A predictor for checkpoint N+1 may use only information that exists when
checkpoint N finishes.

| Measurement | Available at checkpoint N | Notes |
|-------------|---------------------------|-------|
| Checkpoint quality metrics (`loc`, `cc_*`, lint, clones, verbosity, erosion) | Yes | Computed from the checkpoint N snapshot. |
| Transition rework and regression breadth for N-1→N | Yes | Uses snapshots N-1 and N only. |
| Regression transition fields at N | Yes | Uses evaluations N-1 and N. |
| Problem components `V_p`, `E_p`, `H_p`, `R_p`, `G_p`, `I_p`, and `S_p` | No | Averaged over every checkpoint and transition of the problem, including later ones. |
| Agent identity, model, prompt, reasoning level, cost limits | Yes | Fixed run controls. |

## Continuation semantics

Each checkpoint continues from the previous checkpoint's snapshot. Agent
conversation context depends on the harness:

| Harness | Context across checkpoints |
|---------|----------------------------|
| OMP | Fresh session at every checkpoint (`--no-session`); the agent sees only the workspace and the new specification. |
| OpenCode | Continues the previous session (`--continue`). |
| Claude Code | Continues the previous session (`--continue`). |

Cross-harness comparisons therefore mix code inheritance with conversation
inheritance. Controlled continuation studies use a fresh-session harness so the
starting snapshot is the only inherited state.

## Evaluator validity

The problem catalogue is upstream content and is not edited here. Hidden tests
that assert behaviour the specification does not state are intentional
difficulty (agents must infer unstated edge cases). A checkpoint failure is
therefore read against the full test suite, not against the spec text alone.

Evaluator checks that stay inside the harness:

- every reference checkpoint must pass its own tests under `eval-snapshot`;
  a failure is fixed in the harness (environment, locks, plugins, timeouts);
- a reference that also fails upstream is a catalogue defect, reported
  upstream and noted when interpreting affected checkpoints;
- tests that fail across every independent run are listed before results are
  interpreted, without changing the tests.

Results produced while the harness or catalogue was wrong are deleted and the
runs repeated.

## Validation status

| Measurement | Status | Evidence |
|-------------|--------|----------|
| Strict checkpoint solve | Correctness claim | Strict `all-cases` evaluation. |
| Quality components and `I_p` | Descriptive | Predictive and causal validation pending. |
