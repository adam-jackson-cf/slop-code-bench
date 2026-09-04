---
version: 2.0
last_updated: 2026-08-29
---

# Evaluation System Architecture

This guide provides a detailed overview of the pytest-based evaluation system architecture.

## System Overview

The evaluation system uses `PytestRunner` to execute standard pytest tests
against agent submissions. Tests run with an immutable, content-addressed
evaluator environment built by `uv sync --frozen`; the submission's environment
is separate from the trusted test runner.

```
Problem
├── config.yaml              # Problem + checkpoint configuration
├── pyproject.toml           # Evaluator dependencies
├── uv.lock                  # Exact evaluator dependency lock
└── tests/
    ├── conftest.py          # Required fixtures
    ├── test_checkpoint_1.py # Tests for checkpoint 1
    ├── test_checkpoint_2.py # Tests for checkpoint 2
    └── ...
```

## Execution Flow

### High-Level Flow

```
┌─────────────────┐
│  ProblemConfig  │
│  + Checkpoint   │
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│     PytestRunner     │
│                      │
│ 1. Copy tests        │
│ 2. Gen pytest.ini    │
│ 3. Verify/build env  │
│ 4. Execute pytest    │
│ 5. Parse reports     │
│ 6. Categorize        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ CorrectnessResults   │
│ + TestResult[]       │
└──────────────────────┘
```

### Detailed Execution Steps

1. **Test Preparation**
   - Copy test files from `problems/{problem}/tests/` to workspace
   - Only copy tests for checkpoints 0..N based on `include_prior_tests` setting
   - Generate `pytest.ini` with marker registration

2. **Evaluator Environment**
   - Hash `pyproject.toml`, `uv.lock`, declared `test_dependencies`, the
     coverage plugin, and interpreter identity
   - Reuse a fully verified environment with that identity, or build it with
     `uv sync --frozen --no-install-project`
   - Verify the environment inventory, hashes, file modes, and `READY` marker

3. **Command Construction and Execution**
   - Run pytest through the locked evaluator interpreter
   - Pass `--entrypoint` and `--checkpoint` options to pytest
   - Limit conftest discovery to `.evaluation_tests`
   - Configure CTRF and pytest-json-report output paths
   - Keep the submission's dependencies separate from evaluator dependencies

4. **Report Parsing**
   - Parse CTRF JSON report (pytest-json-ctrf plugin)
   - Parse pytest-json-report for detailed failure messages
   - Prefer pytest-json-report (expands parametrized tests)

5. **Test Categorization**
   - Determine `GroupType` for each test based on:
     - Pytest markers (`@pytest.mark.error`, `@pytest.mark.functionality`)
     - Which checkpoint the test file belongs to
   - Aggregate counts by `GroupType`

6. **Result Generation**
   - Create `TestResult` for each test
   - Build `CorrectnessResults` with aggregated statistics

When canonical measurement is requested, the same evaluator runs branch
coverage with the internal audit plugin. The resulting ledger records pytest
phase outcomes, coverage contexts, and process-creation events for regression
attribution.

## Core Components

### PytestRunner (`pytest_runner.py`)

The main orchestrator class that manages the full evaluation lifecycle:

```python
runner = PytestRunner(
    problem=problem_config,
    checkpoint=checkpoint_config,
    environment=env_spec,
    submission_path=Path("experiments/submission/checkpoint_1"),
    evaluator_environment_parent=Path("experiments/run/measurement_analysis"),
)
results = runner.run()
```

**Key Methods:**
- `_copy_tests_from_problem()`: Selectively copy test files
- `_generate_pytest_ini()`: Create pytest.ini with markers
- `_locked_evaluator_python()`: Build or verify the immutable evaluator environment
- `_parse_ctrf_report()`: Parse CTRF JSON output
- `_determine_group_type()`: Categorize tests by markers/checkpoint
- `run()`: Main orchestration method

### Test Categorization Logic

The `_determine_group_type()` method implements categorization rules:

```python
def _determine_group_type(test_checkpoint, markers, current_checkpoint):
    is_current = test_checkpoint == current_checkpoint

    # Rule 1: Prior checkpoint tests ALWAYS become regression (regardless of markers)
    if not is_current:
        return GroupType.REGRESSION

    # Rule 2: Error marker wins for current checkpoint
    if "error" in markers:
        return GroupType.ERROR

    # Rule 3: Explicit regression marker
    if "regression" in markers:
        return GroupType.REGRESSION

    # Rule 4: Check custom markers from problem config
    for marker in markers:
        if marker in problem.markers:
            return problem.markers[marker].group

    # Rule 5: Functionality marker
    if "functionality" in markers:
        return GroupType.FUNCTIONALITY

    # Rule 6: Default to CORE
    return GroupType.CORE
```

### Result Models (`report.py`)

**TestResult**: Individual test outcome
```python
class TestResult(BaseModel):
    id: str                    # Pytest nodeid
    checkpoint: str            # "checkpoint_1", etc.
    group_type: GroupType      # CORE, FUNCTIONALITY, etc.
    status: Literal["passed", "failed", "skipped", "error"]
    duration_ms: float
    file_path: str
    markers: list[str]
    failure_message: str | None
```

**CorrectnessResults**: Aggregated checkpoint results
```python
class CorrectnessResults(BaseModel):
    problem_name: str
    checkpoint_name: str
    duration: float
    tests: list[TestResult]
    pass_counts: dict[GroupType, int]
    total_counts: dict[GroupType, int]
    pytest_exit_code: int
    infrastructure_failure: bool
```

## Pytest Command Structure

The runner builds a command like:

```bash
measurement_analysis/evaluator_environments/<environment_id>/.venv/bin/python \
  -m pytest \
  .evaluation_tests \
  --timeout=30 \
  --entrypoint='python main.py' \
  --checkpoint='checkpoint_1' \
  --confcutdir=.evaluation_tests \
  --ctrf=.scbench/ctrf-report.json \
  --json-report \
  --json-report-file=.scbench/pytest-report.json \
  -vv
```

Canonical coverage runs insert `coverage run --branch -m` before `pytest` and
load the internal `coverage_plugin`.

**Key Options:**
- `--entrypoint`: Command to run submission (passed to test fixtures)
- `--checkpoint`: Current checkpoint name
- `--timeout`: Session-level timeout from checkpoint config
- `--confcutdir`: Prevent agent-authored parent `conftest.py` files from loading
- `--ctrf`: CTRF JSON output path
- `--json-report`: Enable detailed failure reports

## Test Dependencies

Every problem declares evaluator packages in `pyproject.toml` and commits the
matching `uv.lock`. Entries in `config.yaml` `test_dependencies` must also
appear in `[project].dependencies`; they document which locked packages are
problem-specific. The runner never resolves floating dependencies at execution
time.

The standard evaluator set includes pytest, pytest-json-ctrf,
pytest-json-report, pytest-timeout, coverage, and Ruff. Add libraries used by
tests, such as `jsonschema` or `deepdiff`, to the problem project and regenerate
`uv.lock`.

## Exit Codes

| Code | Meaning | Infrastructure Failure? |
|------|---------|------------------------|
| 0 | All tests passed | No |
| 1 | Some tests failed | No |
| 2 | Interrupted | Yes |
| 3 | Internal error | Yes |
| 4 | Usage error | Yes |
| 5 | No tests collected | Yes |

Infrastructure failures set `results.infrastructure_failure = True` and cause
all assessment policies to fail.

## Design Patterns

### Locked Evaluator Isolation

Evaluator environments are immutable and keyed by exact inputs:
- `uv.lock` fixes dependency resolution
- Every installed file and mode is inventoried and verified before reuse
- A completed environment is published only after its `READY` marker is durable
- Solution dependencies do not alter the trusted evaluator

### Marker-Based Categorization

Instead of directory-based grouping, tests use pytest markers:
- Built-in: `@pytest.mark.error`, `@pytest.mark.functionality`, `@pytest.mark.regression`
- Custom markers defined in problem config
- Automatic regression detection for prior checkpoint tests

### Checkpoint Test Selection

When `include_prior_tests=True` (default):
- Copy test files for checkpoints 0..N (current)
- Prior checkpoint tests automatically become REGRESSION type
- Ensures solutions don't break earlier functionality

## Integration Points

- **Execution Module**: `Session` and `EnvironmentSpec` for Docker runtime
- **Configuration**: `ProblemConfig` and `CheckpointConfig` from `config.py`
- **CLI**: `slop-code eval` command uses `run_checkpoint_pytest()`

## Next Steps

- **Configure problems**: [Configuration Guide](configuration.md)
- **Understand results**: [Reporting Guide](reporting.md)
- **Debug failures**: [Troubleshooting Guide](troubleshooting.md)
