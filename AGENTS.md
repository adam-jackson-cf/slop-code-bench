# Repository Guidelines

## Documentation Boundary

- Keep engineering practices and operational instructions in this file.
- Put project overview, repository structure, architecture, workflows, and
descriptions of how the system works in `README.md` or the relevant guide
under `docs/`.
- Do not duplicate this file in tool-specific instruction files; those files
should point to `AGENTS.md`.

## Build, Test, and Development Commands

```bash
uv sync
uv run slop-code --help
uv run slop-code run ...
uv run slop-code eval experiments/<run-dir>
uv run slop-code tools run-case -s experiments/<snapshot> -p <problem> -c <n> -e configs/environments/docker-python3.12-uv.yaml

uv run pytest -q
uv run pytest tests/path/to/test_file.py
uv run ruff check --fix .
```

## Benchmark Operations

- After a benchmark (experiment) completes successfully, use the [`experiment-observations`](./.agents/skills/experiment-observations/SKILL.md) skill to capture observations and surface results to the user.
- Use the [`fault-catalog`](./.agents/skills/fault-catalog/SKILL.md) skill to update the fault catalog and corresponding
Fault Category Records when the observations require it.

## Experiment Snapshot Integrity

- **NEVER** modify experiment snapshots during implementation, remediation,
formatting, linting, type-checking, security hardening, or test repair. They
include intentional challenges and issues to support the benchmark
experiment.
- Experiment snapshots include `tests/agent_runner/resources/**`,
`tests/mining/fixtures/**`, `tests/evaluation/fixtures/**`,
`examples/**/submission/**`, `examples/**/submissions/**`,
`scratch/attempts/**`, `scripts/attempts/**`, `problems/**/solution/**`, and
`problems/**/tests/data/**`.
- **ALWAYS** exclude experiment snapshots from applicable automated quality
gates. If tooling modifies one, restore it byte-for-byte rather than repair
its intentional defects.

## Benchmark Assessment

- **ALWAYS** assess and headline benchmark performance using the strict `all-cases` criterion: a checkpoint is solved only when every evaluated test passes.
- **NEVER** present average test-case pass rate, a permissive policy result, or completed checkpoint count as checkpoints solved.
- `continue_after_test_failure: true` MAY be used only for longitudinal experiments. When used, report both the strict checkpoints-solved result and secondary test-case pass rates.
- **ALWAYS** describe longitudinal runs as full cumulative evaluation with non-blocking checkpoint continuation; never describe them as non-strict assessment.

## Coding Style and Naming Conventions

- Use Python 3.12+, 4-space indentation, and a maximum line length of 80.
- Use `from __future__ import annotations`, `pathlib.Path`, and type
annotations for all functions.
- Use Pydantic models for configuration and
`structlog.get_logger(__name__)` for logging.
- Keep imports on separate lines. Use `snake_case` for modules and `CapWords`
for classes.

## Testing Guidelines

- Use pytest. Test files under `tests/` use `*_test.py` or `test_*.py`.
- Add tests for new behavior and edge cases.
- **NEVER** run a benchmark problem's tests directly with pytest. **ALWAYS**
use `uv run slop-code --quiet eval-snapshot` or
`uv run slop-code --quiet tools run-case`.

## Commit and Pull Request Guidelines

- Use concise Conventional Commit summaries.
- For problem contributions, follow
`docs/contributing-problems/checklist.md`.
- For other pull requests, include a clear description, link relevant issues,
note verification performed, and add screenshots for dashboard or UI
changes.

## Configuration and Credentials

- API keys are provided through environment variables. Do not commit secrets.
- Environment and runtime settings live in `configs/environments/` and
`configs/providers.yaml`.

