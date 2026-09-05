---
name: "run-tests"
description: "Use when evaluating one benchmark snapshot without starting an agent run."
---

# Run benchmark snapshot tests

## Inputs

- snapshot path;
- managed problem name;
- checkpoint index; and
- environment configuration, defaulting to `configs/environments/docker-python3.12-uv.yaml`.

Resolve inputs from repository configuration and experiment artifacts before asking the user.

## Procedure

1. Create a unique output directory. Never overwrite an experiment or prior evaluation directory.
2. Run:

   ```bash
   uv run slop-code --quiet eval-snapshot <snapshot-path> \
     --problem-name <problem-name> \
     --checkpoint <checkpoint-index> \
     --env-config configs/environments/docker-python3.12-uv.yaml \
     --save-dir <unique-output-directory> \
     --json
   ```

3. Read `evaluation.json` and `evaluation.log` from the output directory.
4. If `infrastructure_failure` is true, collection is empty, or required artifacts are missing, report an evaluation infrastructure failure. Do not classify the checkpoint as failed.
5. Otherwise, apply the strict `all-cases` rule: the checkpoint is solved only when every evaluated test passes. Group labels are diagnostic and do not make failures optional.
6. Report the test totals, failed test identities, strict checkpoint result, infrastructure state, and repository-relative output path.

## Rules

- Never run benchmark problem tests directly with pytest.
- Never modify the snapshot, problem definition, tests, or reference solution.
- Never describe completed execution or a permissive pass rate as a solved checkpoint.
- Use `tools run-case` instead when the request requires one isolated case rather than the cumulative checkpoint evaluation.
