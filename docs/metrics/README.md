---
version: 1.0
last_updated: 2026-08-29
---

# Metrics System Documentation

The metrics system automatically measures code quality for agent submissions,
tracking everything from lines of code and cyclomatic complexity to clone
coverage reported by `scb-check`.

## 30-Second Overview

When an agent completes a checkpoint, the metrics system analyzes the submitted code and generates:
- **Line metrics**: LOC, comments, total lines
- **Lint metrics**: Ruff errors and violations
- **Complexity metrics**: Cyclomatic complexity (A-F ratings), nesting depth
- **Composite quality**: Verbosity and erosion from pinned `scb-check`
- **Code quality**: Waste detection (trivial wrappers, single-use functions)
- **Dependencies**: Graph metrics for import relationships

These descriptive results are saved to JSON/JSONL files in each checkpoint's
`quality_analysis/` directory. Canonical benchmark scores are published
separately as verified generations under the run's `measurement_analysis/`.

## Documentation Guide

### Understanding Results at Different Levels

**Checkpoint-level results** (individual checkpoint):
- Want details on test results and quality metrics for a single checkpoint? See [Checkpoint Results](checkpoint-results.md) - covers evaluation.json and quality_analysis/
- Contains correctness (test results) and quality (code metrics) for that checkpoint
- Located in: `checkpoint_N/evaluation.json` and `checkpoint_N/quality_analysis/`

**Descriptive run-level results** (aggregated across all checkpoints):
- Comparing runs or analyzing trends across checkpoints? See [Run-Level Results](run-results.md) - aggregated statistics
- Contains solve rates, average costs, efficiency metrics, quality trends
- Located in: `checkpoint_results.jsonl` and `result.json` at run root

### All Metrics
- **New to metrics?** Start with [Interpreting Results](interpreting-results.md) - explains what each metric means
- **Looking at output files?** See [Output Files Reference](output-files.md) - file locations and formats
- **Need canonical formulas and artifacts?** See [Metrics Reference](../metrics-reference.md)

### Configuration
- **Adjusting thresholds?** Read [Configuration Guide](configuration.md)

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Checkpoint Results** | Correctness (tests) + Quality (code metrics) for a single checkpoint |
| **Run Summary** | Aggregated statistics across all checkpoints and problems |
| **LOC** | Lines of code (source lines, excluding blanks) |
| **Cyclomatic Complexity (CC)** | Number of independent paths through code (A=1-5, F=41+) |
| **Maintainability Index (MI)** | Composite score of code maintainability (A >= 19) |
| **Verbosity** | Code-bloat score produced by pinned `scb-check` |
| **Waste** | Abstraction inefficiencies (trivial wrappers, single-use functions) |
| **Clones** | Clone coverage reported by pinned `scb-check` |
| **Delta Metrics** | Percentage changes between checkpoints |
| **Pass Rate** | Percentage of tests passing by category (CORE, FUNCTIONALITY, etc.) |
| **Solve Rate** | Percentage of checkpoints/problems meeting success criteria |
| **Canonical Score** | Verified benchmark score published under `measurement_analysis/`; higher is better |

## Common Questions

### What metrics indicate good descriptive code quality?
- **CC ratings**: More A/B ratings, fewer D/E/F
- **Lint errors**: Lower is better
- **Descriptive `scb-check` verbosity**: Lower is better
- **Waste metrics**: Fewer trivial wrappers and single-use functions
- **Cloned percentage**: Lower `scb-check` percentage means less duplication

Canonical components use favorable `[0, 1]` orientation, so higher is better.
They are not interchangeable with similarly named descriptive checkpoint
metrics.

### Where do I find metrics for my run?

Metrics are saved at two levels:

**Checkpoint-level** (detailed for single checkpoint):
```
experiments/run_name/problem_name/checkpoint_N/
├── evaluation.json                       # Test results
├── quality_analysis/
│   ├── overall_quality.json              # Aggregated snapshot metrics
│   ├── files.jsonl                       # Per-file metrics
│   └── symbols.jsonl                     # Per-function/class metrics
└── evaluation/
    ├── stdout.txt, stderr.txt, report.json  # Test artifacts
```

**Run-level** (descriptive aggregation and canonical score state):
```
experiments/run_name/
├── checkpoint_results.jsonl       # Descriptive checkpoint metrics
├── result.json                    # Descriptive run summary
└── measurement_analysis/
    ├── current.json               # Current verified generation pointer
    └── generations/<generation_id>/
        ├── manifest.json
        ├── benchmark_score.json   # Eligible generations only
        └── READY
```

Use checkpoint-level files for detailed analysis of a specific checkpoint. Use
`result.json` for descriptive trends and the verified current
`measurement_analysis` generation for canonical comparison.

### How do I compare checkpoints?
Delta metrics (prefixed with `delta.`) show percentage changes:
- `delta.loc`: Lines of code change
- `delta.verbosity`: Verbosity score change
- `delta.churn_ratio`: Code churn (lines added + removed / prior total)

## Code Location

- **Quality metrics computation**: `src/slop_code/metrics/`
  - `driver.py`: Main entry point for measuring quality
  - `languages/`: Language-specific parsers (Python, JavaScript, etc.)
  - `checkpoint/`: Checkpoint-level metrics extraction and delta computation
  - `summary/`: Run-level aggregation and summary statistics
- **Evaluation (test results)**: `src/slop_code/evaluation/report.py`
  - `CorrectnessResults`: Test result model
  - `GroupType`: Test categorization (CORE, FUNCTIONALITY, REGRESSION, ERROR)
  - `PassPolicy`: API enum used by `assessment_policy`
- **Main entry points**:
  - Snapshot quality: `slop_code.metrics.driver.measure_snapshot_quality()`
  - Checkpoint metrics: `slop_code.metrics.checkpoint.driver.get_checkpoint_metrics()`
  - Run summary: `slop_code.metrics.summary.aggregators` module

## Version History

- **v1.1** (2025-12-26): Added checkpoint-results.md and run-results.md documentation for two-level metrics hierarchy
- **v1.0** (2025-12-17): Initial metrics documentation
