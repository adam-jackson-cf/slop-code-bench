<div align="center">
<h1 > SlopCodeBench (SCBench)</h1>

  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
  [![GitHub stars](https://img.shields.io/github/stars/SprocketLab/slop-code-bench)](https://github.com/SprocketLab/slop-code-bench/stargazers)
  [![DOI](https://zenodo.org/badge/1118434028.svg)](https://doi.org/10.5281/zenodo.19257129)

  [🌐 Website](https://www.scbench.ai) | [📄 Paper](https://arxiv.org/abs/2603.24755) | [📝 Blog Post](https://gabeorlanski.github.io/posts/slop-code-bench)
</div>

![](assets/overview.png)
---

**SlopCodeBench** evaluates coding agents under iterative specification refinement: the agent implements a spec, then extends its own code as the spec changes. This exposes behaviors that single-shot benchmarks cannot measure, including path dependence, non-convergence, and trade-offs between explicit handling and structural stability. We release SCBench as an open, community-driven evaluation primitive rather than a finalized benchmark.


Problem definitions now live in the separate [scb-problems repository](https://github.com/SprocketLab/scb-problems) and are also available as a [Harbor dataset](https://registry.harborframework.com/datasets/gabeorlanski/slopcodebench/latest). We actively want more problems; follow [the creating a problem guide](/docs/contributing-problems/) and open a PR there.

> [!NOTE]
> This is an initial release. We're actively developing and welcome feedback via [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues).

## Repository layout

- `src/slop_code/` contains the core library, including the CLI, agent
  runners, execution environments, evaluation, metrics, and dashboard.
- `tests/` contains the pytest suite and generally mirrors the core library.
- `configs/` contains agent, model, provider, prompt, environment, and run
  configuration.
- `.agents/skills/` contains the local experiment lifecycle, snapshot
  evaluation, observations, and fault-catalog workflows.
- `experiment_analysis/` contains dated experiment observations, the fault
  catalog, and detailed Fault Category Records.
- `docs/` contains guides for agents, evaluation, execution, metrics, commands,
  and problem authoring.
- `experiments/` contains benchmark run artifacts and evaluation results.
- `assets/` contains project images and other static media.

Dashboard visualization is documented with the `viz diff` command in
[`docs/commands/viz.md`](docs/commands/viz.md).

## Architecture

`slop-code` resolves run configuration and the managed problem catalog, then
coordinates five principal subsystems:

- `agent_runner` starts and resumes coding-agent processes.
- `execution` provides isolated local or Docker workspaces.
- `evaluation` collects and executes cumulative checkpoint tests.
- `metrics` records code-quality evidence and publishes immutable scoring
  generations.
- `dashboard` and `visualization` consume persisted results without becoming
  scoring authorities.

Problem definitions are versioned independently in `scb-problems`; this
repository owns the runner, evaluation semantics, scoring, and reporting.

## Configuration

Reusable agents, environments, prompts, providers, models, and run examples
live under `configs/`. Run configuration uses `save_dir` and `save_template`
for output placement. Values resolve in this order: command-line overrides,
command-line flags, configuration file, then built-in defaults.

See [`docs/commands/run.md`](docs/commands/run.md) for every field and override.

## Local skills

- `experiment-lifecycle` defines, preflights, launches, monitors, controls, and
  hands off single-run or matrix experiments.
- `run-tests` evaluates one saved snapshot through the isolated evaluator.
- `experiment-observations` publishes evidence-backed analysis from terminal
  artifacts.
- `fault-catalog` selects fault-driven targets and reconciles supported
  findings.

Problem-authoring and reference-solution workflows live with the source
problems in the `scb-problems` repository.

## Experiment lifecycle

1. Define the objective, any declared experimental variable, and fixed
   controls in the existing run configuration.
2. Preflight the exact command with `uv run slop-code run ... --dry-run`.
3. Launch the same command without `--dry-run`. The resolved configuration and
   persisted run artifacts are the canonical experiment record.
4. Use `experiment-lifecycle` to inspect, resume, stop, restart, or hand off
   executions without overwriting prior artifacts.
5. After all configured executions become terminal, use
   `experiment-observations`; use `fault-catalog` when observations support a
   catalog transition.

Benchmark assessment is always strict `all-cases`: a checkpoint is solved only
when every evaluated test passes. Longitudinal runs may set
`continue_after_test_failure: true` to continue execution, but this does not
make assessment permissive.

## Prerequisites

Before installing, ensure you have:
- **Python 3.12+** installed
- **Docker** installed and running ([Get Docker](https://docs.docker.com/get-docker/))
- An **API key** for your chosen agent (e.g., Anthropic, OpenAI, Google)
- **8GB+ RAM** recommended for running evaluations
- **10GB+ disk space** for Docker images and workspaces

## 🚀 Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/SprocketLab/slop-code-bench.git && cd slop-code-bench && uv sync
export ANTHROPIC_API_KEY="your-key"

# Preflight without consuming model tokens
uv run slop-code run \
  --config configs/runs/example_full.yaml \
  --problem file_backup \
  --dry-run

# Start the experiment
uv run slop-code run \
  --config configs/runs/example_full.yaml \
  --problem file_backup
```

The default output layout is:

```text
experiments/<model>/<agent>-<version>_<prompt>_<thinking>_<timestamp>/
```

The agent version segment is omitted when the selected agent has no version.
Every run persists its resolved configuration, provenance, checkpoint
artifacts, evaluations, summaries, and scoring evidence beneath that directory.
Use a distinct output location for every restart or comparison member.

### Troubleshooting

**Docker not found:**
```bash
# Check Docker is running
docker ps
# If not running, start Docker Desktop or daemon
```

**API key not found:**

```bash
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY is set"
else
  echo "ANTHROPIC_API_KEY is not set"
fi
```

**Out of disk space:**
```bash
# Clean up old Docker images
docker system prune -a
```

For more issues, see [GitHub Issues](https://github.com/SprocketLab/slop-code-bench/issues).

## 📊 Evaluation

**Evaluate a run:**
```bash
uv run slop-code eval experiments/your-run-directory/
```

**Grade code quality with LLM judge:**
```bash
uv run slop-code metrics judge \
  --rubric configs/rubrics/llm_judge.jsonl \
  --model <model on openrouter> \
  --criteria-template configs/rubrics/templates/criteria_with_pn.j2 \
  --prefix-template configs/rubrics/templates/no_expl.j2
```

## Contributing

We welcome contributions. Two ways to help:

- **Add problems** — Expand the benchmark with new evaluation scenarios in the [scb-problems repository](https://github.com/gabeorlanski/scb-problems), also published as a [Harbor dataset](https://registry.harborframework.com/datasets/gabeorlanski/slopcodebench/latest). See the [Problem Tutorial](docs/problems/tutorial.md) and [Contributing Guide](CONTRIBUTING.md).
- **Add agents** — Integrate new coding agents. See the [Agent Guide](docs/agents/README.md) and [Contributing Guide](CONTRIBUTING.md).

This is early-stage software. Your contributions will shape its direction.

## Documentation

| Guide | Description |
|-------|-------------|
| [❓ FAQ](docs/FAQ.md) | Frequently asked questions |
| [📖 Problem Tutorial](docs/problems/tutorial.md) | Create your first problem (30 min hands-on) |
| [📋 Quick Reference](docs/problems/quick-reference.md) | One-page cheat sheet for problem authoring |
| [🤖 Agent Guide](docs/agents/README.md) | Configure agents, models, and credentials |
| [🏗️ Architecture](docs/execution/README.md) | How sessions, workspaces, and runtimes work |
| [✅ Evaluation System](docs/evaluation/README.md) | Test cases, adapters, loaders, and verifiers |
| [💡 Problem Design](docs/contributing-problems/README.md) | What makes a good evaluation problem |
| [⚠️ Known Issues](docs/KNOWN_ISSUES.md) | Current limitations and workarounds |
| [📊 Commands](docs/commands/README.md) | CLI command reference (run, eval, metrics, viz, etc.) |

## Citing Us

If you found this useful, please cite us as:
```bibtex
@article{Orlanski2025SlopCodeBench,
  author = {Orlanski, Gabriel and Roy, Devjeet and Yun, Alexander and Shin, Changho and Gu, Alex and Ge, Albert and Adila, Dyah and Albarghouthi, Aws and Sala, Frederic},
  title = {{SlopCodeBench: Measuring Code Erosion Under Iterative Specification Refinement}},
  journal = {arXiv preprint arXiv:2603.24755},
  year = {2025},
  url = {https://arxiv.org/abs/2603.24755}
}
```
