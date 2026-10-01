---
version: 1.0
last_updated: 2026-09-30
---

# OMP Agent

The OMP agent runs the [oh-my-pi](https://github.com/can1357/oh-my-pi) coding
agent (`omp`, a Pi fork) headlessly (`omp -p --mode json`). Its purpose is to
compare **models** under identical conditions, including subscription-served
models (`openai-codex/*`, `anthropic/*`); OMP is only the harness.

Inside the container OMP is vanilla: a fresh config directory, no extension,
skill or rule discovery, no advisor, no session persistence, and stdin closed.

## Credentials: host auth broker

Refresh tokens never enter the container. The operator runs the broker on the
host, which opens `~/.omp/agent/agent.db`, holds the refresh tokens and
refreshes them. The container receives only `OMP_AUTH_BROKER_URL` and
`OMP_AUTH_BROKER_TOKEN` and resolves a redacted snapshot through the broker.

```bash
# Prerequisite (operator, once per session). Loopback is enough on OrbStack:
# containers reach it as host.docker.internal.
omp auth-broker serve --bind=127.0.0.1:8765
```

The bearer token is read from `~/.omp/auth-broker.token` (file provider
`omp_broker` in `configs/providers.yaml`). If your Docker runtime cannot reach
host loopback, bind a wider interface (the broker is bearer-protected) and set
`broker_url` in the agent config.

## Configuration

```yaml
# configs/agents/omp.yaml
type: omp
binary: omp
version: 18.4.4           # release pinned in the Docker image
timeout: 7200
broker_url: http://host.docker.internal:8765
extra_args: []
env: {}
provider: null            # optional OMP provider override
thinking: null            # optional low|medium|high|xhigh override
```

The image installs the `omp-linux-<arch>` binary from the
`can1357/oh-my-pi` release `v<version>` and verifies it against the release's
`SHA256SUMS.txt`.

## Models and thinking

Model configs declare the OMP provider under `agent_specific.omp`:

```yaml
provider: omp_broker
agent_specific:
  omp:
    provider: openai-codex   # or anthropic
    model: gpt-6-luna
```

Available: `gpt-6-sol`, `gpt-6.1-sol`, `gpt-6-luna`, `gpt-6-astra`,
`claude-sonnet-5-5`, `claude-opus-5-5`.

The SCB thinking preset maps to an OMP effort suffix:
`--model <provider>/<model>:<low|medium|high|xhigh>`. `none`, `disabled`, an
unset preset and token-budget thinking are rejected with a configuration error:
these models have no off mode, and `:off` on Codex would silently use the
server default.

## Running

```bash
uv run slop-code run \
  --agent configs/agents/omp.yaml \
  --model omp_broker/<model> \
  --environment configs/environments/docker-python3.12-uv.yaml \
  --problem <problem> \
  thinking=<low|medium|high|xhigh>
```

Artifacts per checkpoint: `stdout.jsonl` (JSON events, streaming deltas
removed; parsed by the Pi trajectory parser, the event format is shared),
`stderr.log`, `prompt.txt`. Cost is taken from OMP's reported
`message_end.usage.cost.total`.
