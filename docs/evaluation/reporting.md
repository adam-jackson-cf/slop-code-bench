---
version: 2.0
last_updated: 2026-10-01
---

# Reporting Guide

This guide covers the reporting system for pytest-based evaluation, including result models, assessment policies, and export formats.

## Overview

The reporting system aggregates pytest results into structured reports:

- **TestResult**: Individual test outcome with categorization
- **CorrectnessResults**: Aggregated checkpoint results with pass/fail counts
- **PassPolicy**: API enum used by `assessment_policy`
- **Export formats**: JSON for storage and analysis

## Result Models

### TestResult

Individual test outcome from pytest execution:

```python
class TestResult(BaseModel):
    id: str                    # Pytest nodeid (e.g., "test_basic[case1]")
    checkpoint: str            # Checkpoint name (e.g., "checkpoint_1")
    group_type: GroupType      # CORE, FUNCTIONALITY, REGRESSION, or ERROR
    status: Literal["passed", "failed", "skipped", "error"]
    duration_ms: float         # Execution time in milliseconds
    file_path: str             # Test file path
    markers: list[str]         # Pytest markers (e.g., ["functionality"])
    failure_message: str | None  # Failure details if failed/errored
```

**Status Values:**
- `passed`: Test passed all assertions
- `failed`: Test failed one or more assertions
- `skipped`: Test was skipped (e.g., `pytest.skip()`)
- `error`: Test had an error during setup/teardown

### CorrectnessResults

Aggregated results for a checkpoint evaluation:

```python
class CorrectnessResults(BaseModel):
    # Metadata
    problem_name: str          # Problem identifier
    problem_version: int       # Problem version number
    checkpoint_name: str       # Checkpoint name
    checkpoint_version: int    # Checkpoint version number
    duration: float            # Total evaluation time (seconds)
    entrypoint: str            # Command used to run submission

    # Test results
    tests: list[TestResult]    # All individual test results

    # Aggregated counts
    pass_counts: dict[GroupType, int]   # Passed tests by type
    total_counts: dict[GroupType, int]  # Total tests by type

    # Pytest metadata
    pytest_exit_code: int      # Pytest exit code (0=success, 1=failures)
    pytest_collected: int      # Number of tests collected
    infrastructure_failure: bool  # True if pytest itself failed
    # Canonical measurement provenance (populated for measurement runs)
    coverage_ledger: dict | None   # From the separate coverage pass only
    evaluator_environment: dict | None
    platform_identity: dict | None
    problem_config: dict | None
    test_corpus: dict | None
    invocation: dict | None        # command (correctness) + coverage_command
    environment_fingerprint: str | None
```

### GroupType

Test categorization enum:

```python
class GroupType(str, Enum):
    CORE = "Core"              # Must-pass tests
    FUNCTIONALITY = "Functionality"  # Nice-to-have tests
    REGRESSION = "Regression"  # Tests from prior checkpoints
    ERROR = "Error"            # Error-handling tests
```

## Accessing Results

### Basic Access

```python
from slop_code.evaluation import run_checkpoint_pytest

# Run evaluation
results = run_checkpoint_pytest(...)

# Check if checkpoint passed
if results.is_solved():
    print("Checkpoint passed!")

# Get pass rates
core_passed = results.pass_counts.get(GroupType.CORE, 0)
core_total = results.total_counts.get(GroupType.CORE, 0)
print(f"Core: {core_passed}/{core_total}")
```

### Iterate Over Tests

```python
# All tests
for test in results.tests:
    status = "PASS" if test.status == "passed" else "FAIL"
    print(f"{status} {test.id} ({test.group_type})")

# Failed tests only
failed = [t for t in results.tests if t.status == "failed"]
for test in failed:
    print(f"FAILED: {test.id}")
    if test.failure_message:
        print(f"  {test.failure_message[:200]}")
```

### Filter by GroupType

```python
# Get only core tests
core_tests = [t for t in results.tests if t.group_type == GroupType.CORE]

# Get only regression tests
regression_tests = [t for t in results.tests if t.group_type == GroupType.REGRESSION]

# Count by group type
from collections import Counter
type_counts = Counter(t.group_type for t in results.tests)
```

### Check Infrastructure Failures

```python
if results.infrastructure_failure:
    print("Pytest failed to run properly!")
    print(f"Exit code: {results.pytest_exit_code}")
    print(f"Collected: {results.pytest_collected} tests")
```

## Assessment Policy

Checkpoint success is strict `assessment_policy: all-cases`, the only supported
value. `CorrectnessResults.is_solved()` and `PassPolicy.ALL_CASES.check()`
expose the same rule to Python callers.

### Rule

A checkpoint is solved only when every evaluated test in every group (CORE,
FUNCTIONALITY, REGRESSION, ERROR) passes. Group labels are diagnostic; ERROR
tests are not assumed to fail. Infrastructure failures always fail, and a
checkpoint with no evaluation result is not solved.

```python
if results.is_solved():
    print("Checkpoint solved!")

# Or from raw counts
from slop_code.evaluation import PassPolicy

passed = PassPolicy.ALL_CASES.check(results.pass_counts, results.total_counts)
```

Any other `assessment_policy` value in run configuration is rejected.

## Export Formats

### Saving Results

```python
# Save to directory
results.save(Path("experiments/checkpoint_1"))

# Creates:
#   experiments/checkpoint_1/evaluation.json    # Main results
#   experiments/checkpoint_1/evaluation/stdout.txt   # Pytest stdout
#   experiments/checkpoint_1/evaluation/stderr.txt   # Pytest stderr
#   experiments/checkpoint_1/evaluation/report.json  # Slim pytest-json-report
```

### JSON Structure (evaluation.json)

```json
{
  "problem_name": "file_backup",
  "problem_version": 1,
  "checkpoint_name": "checkpoint_1",
  "checkpoint_version": 1,
  "duration": 12.34,
  "entrypoint": "python main.py",
  "tests": {
    "checkpoint_1-Core": {
      "passed": ["test_core_cases[basic]"],
      "failed": [],
      "skipped": []
    },
    "checkpoint_1-Error": {
      "passed": [],
      "failed": ["test_error_cases[invalid_input]"],
      "skipped": []
    }
  },
  "pass_counts": {
    "Core": 5,
    "Functionality": 3,
    "Error": 1
  },
  "total_counts": {
    "Core": 5,
    "Functionality": 4,
    "Error": 2
  },
  "pytest_exit_code": 1,
  "pytest_collected": 11,
  "infrastructure_failure": false,
  "coverage_ledger": null,
  "evaluator_environment": null,
  "environment_fingerprint": null
}
```

### Loading Results

```python
import json
from pathlib import Path

# Load from JSON
with open("experiments/checkpoint_1/evaluation.json") as f:
    data = json.load(f)

# Access fields
print(f"Problem: {data['problem_name']}")
print(f"Passed core: {data['pass_counts'].get('Core', 0)}")
print(f"Total core: {data['total_counts'].get('Core', 0)}")
```

## Diagnostic Information

### Pytest Output

Stdout and stderr are saved separately (not in evaluation.json):

```python
# Read pytest output
stdout = Path("experiments/checkpoint_1/evaluation/stdout.txt").read_text()
stderr = Path("experiments/checkpoint_1/evaluation/stderr.txt").read_text()

# Look for collection info
if "collected" in stdout:
    print("Tests were collected successfully")
```

### Failure Messages

```python
# Print failure details
for test in results.tests:
    if test.status in ("failed", "error") and test.failure_message:
        print(f"\n{test.id}:")
        print(test.failure_message)
```

### CTRF Report

The raw CTRF (Common Test Report Format) report is saved for detailed analysis:

```python
import json

with open("experiments/checkpoint_1/evaluation/report.json") as f:
    ctrf = json.load(f)

# Access raw test data
for test in ctrf.get("results", {}).get("tests", []):
    print(f"{test['name']}: {test['status']}")
```

## Analytics Examples

### Summary Report

```python
def print_summary(results):
    total_passed = sum(results.pass_counts.values())
    total_count = sum(results.total_counts.values())
    passed = results.is_solved()

    print(f"{'='*50}")
    print(f"Problem: {results.problem_name}")
    print(f"Checkpoint: {results.checkpoint_name}")
    print(f"{'='*50}")
    print(f"Status: {'PASS' if passed else 'FAIL'}")
    print(f"Tests: {total_passed}/{total_count} passed")
    print(f"Duration: {results.duration:.2f}s")
    print(f"{'='*50}")

    for group_type in GroupType:
        passed = results.pass_counts.get(group_type, 0)
        total = results.total_counts.get(group_type, 0)
        if total > 0:
            print(f"{group_type.value}: {passed}/{total}")
```

### Failure Analysis

```python
from collections import defaultdict

def analyze_failures(results):
    failures_by_type = defaultdict(list)

    for test in results.tests:
        if test.status != "passed":
            failures_by_type[test.group_type].append(test)

    print("Failures by group type:")
    for group_type, tests in failures_by_type.items():
        print(f"\n{group_type.value}: {len(tests)} failures")
        for test in tests[:5]:  # Show first 5
            print(f"  - {test.id}: {test.status}")
```

### Compare Runs

```python
import json
from pathlib import Path

def compare_runs(dir1: Path, dir2: Path):
    with open(dir1 / "evaluation.json") as f:
        run1 = json.load(f)
    with open(dir2 / "evaluation.json") as f:
        run2 = json.load(f)

    for group_type in ["Core", "Functionality", "Regression", "Error"]:
        p1 = run1["pass_counts"].get(group_type, 0)
        t1 = run1["total_counts"].get(group_type, 0)
        p2 = run2["pass_counts"].get(group_type, 0)
        t2 = run2["total_counts"].get(group_type, 0)

        if t1 > 0 or t2 > 0:
            print(f"{group_type}: {p1}/{t1} -> {p2}/{t2}")
```

## Next Steps

- **Debug failures**: [Troubleshooting Guide](troubleshooting.md)
- **Understand architecture**: [Architecture Guide](architecture.md)
- **Configure problems**: [Configuration Guide](configuration.md)
