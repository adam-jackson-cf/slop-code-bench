# Initiate Matrix Runbook

## Objective

Start a new equivalent full-suite matrix using repository-resolved values.

## Procedure

1. Resolve the fixture, seed, agent harness, environment, prompt, reasoning level, checkpoint sequence, model set, runner revision, and fixture revision from repository configuration and experiment records.
2. Preserve those control variables. Change only the explicitly requested experimental variable. Configure `assessment_policy: all-cases` and `continue_after_test_failure: true`.
3. Verify the fixture, container runtime, pinned harness version, model configurations, unique output directory per model, and credentials without displaying credential contents.
4. When a required tool presents choices, select its recommended option as approved. Ask only when repository evidence cannot resolve materially different choices and no recommended option exists.
5. Launch independent model runs concurrently when local capacity supports it, using the repository's persistent long-running process convention. Do not switch models during a cumulative run or reuse a prior mutable workspace.
6. Record the resolved configuration, runner and fixture revisions, model identity, pricing metadata, and start time for each run.
7. Confirm each member reaches its first checkpoint before reporting that the matrix started.

## Output

Report the started matrix members and their execution identifiers or relative output locations. Use the status runbook for later progress requests.
