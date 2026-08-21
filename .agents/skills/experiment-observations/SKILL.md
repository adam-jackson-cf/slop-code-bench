---
name: "experiment-observations"
description: "Analyze cumulative coding-agent experiments. USE WHEN comparing model strengths, weaknesses, and long-term codebase inertia from benchmark results."
---

# Task

## Inputs

- Locate the persisted experiment manifests, run summaries, checkpoint results, evaluations, quality metrics, and telemetry.
- Use the experiment plan to establish model identities, checkpoint order, pass policy, pricing basis, fixture, seed, and other comparison constraints.
- Do not infer missing measurements or present unavailable values as zero.

## Analysis

- Compare aggregate cumulative pass rate, final cumulative pass rate, current-checkpoint correctness, regression retention, and error-handling performance.
- Trace failures and retained behavior by checkpoint of origin to identify persistent regression debt and recovery.
- Compare code growth, cyclomatic complexity, high-complexity functions, lint density, cyclic dependency mass, token usage, API-equivalent cost, inference duration, and wall duration where available.
- Distinguish immediate feature success from preservation of prior behavior.
- Identify the strongest model for sustained correctness and separately identify the best cost-quality compromise.
- Describe each model’s strengths, weaknesses, failure concentrations, recovery behavior, and structural tradeoffs.
- Extract cross-model trends and explain behavioral, structural, and contextual forms of long-term codebase inertia.
- State limitations arising from problem count, seeds, run count, thinking level, pass policy, or unavailable metrics.

## Findings File

- Create the repository-root directory `.experiments` when it does not exist.
- Use the filename `.experiments/<ddMMyy>-exp-observations-<NNN>.md`.
- Format `<NNN>` as a zero-padded three-digit sequence.
- Find files matching the current date’s `<ddMMyy>-exp-observations-*.md` pattern.
- Set `<NNN>` to one greater than the highest valid sequence for that date, starting at `001`.
- Ignore malformed filenames when calculating the sequence.
- Create a new file; never overwrite an existing observations file.
- If the selected path already exists, recalculate the sequence before writing.
- Structure the file with: question or objective, bottom line, comparison table, model profiles, cross-model trends, long-term codebase inertia, practical model selection, and limitations.
- Keep conclusions evidence-first and distinguish measured results from interpretation.
- Include exact artifact-relative paths or experiment identifiers needed to trace the analysis.

## Validation

- Verify every quantitative claim against persisted artifacts.
- Recalculate percentages, totals, deltas, ratios, and rankings rather than copying unsupported summaries.
- Check that model comparisons use equivalent checkpoints and measurement definitions.
- Confirm the filename matches `ddMMyy-exp-observations-NNN.md`, uses the current local date, contains the next three-digit sequence, and resides under `.experiments`.
- Confirm no existing observations file was overwritten.
- Report the generated file path and concise validation status without creating a generation summary or retained output-contract artifact.
