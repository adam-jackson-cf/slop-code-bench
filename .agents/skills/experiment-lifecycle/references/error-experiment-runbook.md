# Experiment Error Runbook

## Objective

Stop and report an execution whose model or harness cannot perform the configured experiment while preserving evidence and experimental controls.

Model unavailability or harness failures cause immediate stopping of an experiment and must surface to the user.

## Trigger Conditions

- The configured model is absent from the authenticated harness catalog or rejected as unavailable, unknown, unauthorized, or unsupported.
- The harness fails to start, crashes, exits nonzero, emits a protocol or server error, or produces no usable inference result.
- Authentication, container startup, or another harness prerequisite prevents inference.

A benchmark assessment failure is not a harness failure. Apply the configured assessment and continuation policies to valid model output.

## Procedure

1. Stop the affected execution and its owned child processes or containers immediately. Do not retry, resume, or replace the model, harness, harness version, controls, output directory, or workspace in place.
2. Preserve the execution directory and all available configuration, logs, error events, server references, token and step counts, and terminal output. Never delete, overwrite, or repurpose failed-run artifacts.
3. Identify the primary failure at the earliest failed stage. Report later evaluator, scoring, or finalization errors separately; do not substitute them for the inference failure.
4. Mark the execution as an experiment-process failure, not a benchmark result. Exclude it from observations, comparisons, and aggregate scores.
5. Surface the failure to the user immediately. Report the execution identity, model, harness and version, failed stage, exact error, generated tokens and steps, process state, and repository-relative artifact location.
6. State the bounded diagnosis supported by artifacts. If only provider-side logs can establish the root cause, include the available error references and name provider logs as the missing evidence.
7. Propose remediation without applying a control change. Changing a model, harness, harness version, problem revision, environment, prompt, reasoning level, assessment policy, or continuation behavior requires explicit user direction.
8. After remediation is authorized and verified, restart as a new execution with a distinct output location and process identity. Retain the failed execution unchanged.

## Output

Return the stopped state, primary failure, bounded diagnosis, preserved artifact location, and the exact decision required before any replacement execution can start.
