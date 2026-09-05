# run-tests

## Overview

Runs one benchmark snapshot through the canonical `eval-snapshot` command in the configured isolated environment. It reports infrastructure state and applies strict all-cases checkpoint interpretation.

## When to use it

- Evaluate a saved snapshot for one problem checkpoint.
- Inspect failed test identities without starting an agent run.
- Distinguish evaluation infrastructure failure from checkpoint failure.

## Example prompts

- "Evaluate this checkpoint snapshot."
- "Run the cumulative tests for this saved snapshot."
- "Show whether this evaluation failed in the solution or infrastructure."
