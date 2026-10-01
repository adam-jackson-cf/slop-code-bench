"""Unit tests for the OMP agent."""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
import yaml

from slop_code.agent_runner.agents.omp import OmpAgent
from slop_code.agent_runner.agents.omp import OmpConfig
from slop_code.agent_runner.agents.omp import OmpParser
from slop_code.agent_runner.agents.omp.agent import BROKER_TOKEN_ENV
from slop_code.agent_runner.agents.omp.agent import BROKER_URL_ENV
from slop_code.agent_runner.agents.pi import PiParser
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import build_agent_config
from slop_code.agent_runner.trajectory_parsing import parse_trajectory
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.execution import DockerConfig
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult

if TYPE_CHECKING:
    from slop_code.execution import Session

TOKEN = "broker-token-value-123456"  # noqa: S105

# Real assistant ``message_end`` captured from
# ``omp -p --model openai-codex/gpt-6-luna:low --mode json "Reply ok"``
# (OMP 18.4.4); only the opaque textSignature was dropped.
REAL_MESSAGE_END = (
    '{"type":"message_end","message":{"role":"assistant","content":'
    '[{"type":"text","text":"ok"}],"api":"openai-codex-responses",'
    '"provider":"openai-codex","model":"gpt-6-luna","usage":{"input":8638,'
    '"output":5,"cacheRead":0,"cacheWrite":0,"totalTokens":8643,"cost":'
    '{"input":0.0008638000000000001,"output":2.4999999999999998e-06,'
    '"cacheRead":0,"cacheWrite":0,"total":0.0008663000000000001}},'
    '"stopReason":"stop","timestamp":1790765627802,"credentialId":4,'
    '"responseId":"resp_0df73fd4abc1e91b016abcea3c632087d29b9da529591195e2",'
    '"duration":1658.8939999999998,"ttft":1534.893958,'
    '"completedAt":1790765629462}}'
)


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []
        self.cleaned = False
        self.last_stream_args: tuple[str, dict, float | None] | None = None

    def stream(
        self,
        command: str,
        env: dict,
        timeout: float | None,
    ) -> Iterable[RuntimeEvent]:
        self.last_stream_args = (command, env, timeout)
        yield from self.events

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class FakeSession:
    runtime: FakeRuntime
    working_dir: Path
    spec: DockerEnvironmentSpec | None = None
    last_spawn_env_vars: dict[str, str] | None = None
    last_spawn_mounts: dict[str, object] | None = None

    def spawn(self, **kwargs: object) -> FakeRuntime:
        self.last_spawn_env_vars = dict(
            cast("dict[str, str]", kwargs.get("env_vars") or {})
        )
        self.last_spawn_mounts = dict(
            cast("dict[str, object]", kwargs.get("mounts") or {})
        )
        return self.runtime


@pytest.fixture
def cost_limits() -> AgentCostLimits:
    return AgentCostLimits(
        step_limit=10, cost_limit=100.0, net_cost_limit=200.0
    )


@pytest.fixture
def config(cost_limits: AgentCostLimits) -> OmpConfig:
    return OmpConfig(type="omp", version="18.4.4", cost_limits=cost_limits)


@pytest.fixture
def model_def() -> ModelDefinition:
    return ModelDefinition(
        internal_name="gpt-6-luna",
        provider="omp_broker",
        pricing=APIPricing(
            input=0.1, output=0.5, cache_read=0.01, cache_write=0
        ),
        agent_specific={
            "omp": {"provider": "openai-codex", "model": "gpt-6-luna"}
        },
    )


@pytest.fixture
def credential() -> ProviderCredential:
    return ProviderCredential(
        provider="omp_broker",
        credential_type=CredentialType.FILE,
        value=f"{TOKEN}\n",
        source="/home/u/.omp/auth-broker.token",
        destination_key="",
    )


def _make_agent(
    config: OmpConfig,
    model_def: ModelDefinition,
    credential: ProviderCredential,
    **kwargs: object,
) -> OmpAgent:
    agent = OmpAgent._from_config(
        config=config,
        model=model_def,
        credential=credential,
        problem_name="p",
        verbose=False,
        image="omp-test-image",
        **kwargs,  # type: ignore[arg-type]
    )
    assert isinstance(agent, OmpAgent)
    return agent


def _finished(stdout: str, exit_code: int = 0) -> RuntimeEvent:
    return RuntimeEvent(
        kind="finished",
        result=RuntimeResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr="warn\n",
            setup_stdout="",
            setup_stderr="",
            elapsed=0.1,
            timed_out=False,
        ),
    )


class TestOmpConfig:
    def test_default_yaml_loads(self) -> None:
        data = yaml.safe_load(Path("configs/agents/omp.yaml").read_text())
        loaded = build_agent_config(data)
        assert isinstance(loaded, OmpConfig)
        assert loaded.version == "18.4.4"
        assert loaded.timeout == 7200
        assert loaded.broker_url == "http://host.docker.internal:8765"

    def test_docker_file_installs_pinned_verified_release(
        self, config: OmpConfig
    ) -> None:
        dockerfile = config.get_docker_file("base-image:latest")
        assert dockerfile is not None
        assert "FROM base-image:latest" in dockerfile
        assert "releases/download/v18.4.4" in dockerfile
        assert "omp-linux-arm64" in dockerfile
        assert "omp-linux-x64" in dockerfile
        assert "sha256sum --check" in dockerfile
        assert dockerfile.rstrip().splitlines()[-2:] == [
            "USER agent",
            "WORKDIR /workspace",
        ]


class TestModelConfigs:
    @pytest.mark.parametrize(
        ("name", "omp_provider"),
        [
            ("gpt-6-sol", "openai-codex"),
            ("gpt-6.1-sol", "openai-codex"),
            ("gpt-6-luna", "openai-codex"),
            ("gpt-6-astra", "openai-codex"),
            ("claude-sonnet-5-5", "anthropic"),
            ("claude-opus-5-5", "anthropic"),
        ],
    )
    def test_catalog_models_resolve_for_omp(
        self,
        config: OmpConfig,
        credential: ProviderCredential,
        name: str,
        omp_provider: str,
    ) -> None:
        model = ModelCatalog.get(name)
        assert model is not None
        agent = _make_agent(config, model, credential, thinking_preset="high")
        assert agent.model_selector == f"{omp_provider}/{name}:high"


class TestEffortResolution:
    @pytest.mark.parametrize("preset", ["low", "medium", "high", "xhigh"])
    def test_presets_become_model_suffix(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
        preset: str,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset=preset
        )
        assert agent.model_selector == f"openai-codex/gpt-6-luna:{preset}"

    @pytest.mark.parametrize("preset", ["disabled", "none", None])
    def test_missing_or_off_thinking_is_rejected(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
        preset: str | None,
    ) -> None:
        with pytest.raises(ValueError, match="no off mode|explicit reasoning"):
            _make_agent(config, model_def, credential, thinking_preset=preset)

    def test_token_budget_thinking_is_rejected(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        with pytest.raises(ValueError, match="token-budget"):
            _make_agent(config, model_def, credential, thinking_max_tokens=4096)

    def test_config_thinking_wins(
        self,
        cost_limits: AgentCostLimits,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        cfg = OmpConfig(
            type="omp",
            version="18.4.4",
            thinking="xhigh",
            cost_limits=cost_limits,
        )
        agent = _make_agent(cfg, model_def, credential, thinking_preset="low")
        assert agent.model_selector.endswith(":xhigh")


class TestFromConfigValidation:
    def test_requires_broker_credential(
        self, config: OmpConfig, model_def: ModelDefinition
    ) -> None:
        env_cred = ProviderCredential(
            provider="anthropic",
            credential_type=CredentialType.ENV_VAR,
            value="sk",
            source="ANTHROPIC_API_KEY",
            destination_key="ANTHROPIC_API_KEY",
        )
        with pytest.raises(ValueError, match="omp_broker"):
            _make_agent(config, model_def, env_cred, thinking_preset="low")

    def test_requires_omp_provider_in_model(
        self, config: OmpConfig, credential: ProviderCredential
    ) -> None:
        bare = ModelDefinition(
            internal_name="x",
            provider="omp_broker",
            pricing=APIPricing(input=1, output=1, cache_read=0, cache_write=0),
        )
        with pytest.raises(ValueError, match="agent_specific.omp.provider"):
            _make_agent(config, bare, credential, thinking_preset="low")

    def test_requires_image(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        with pytest.raises(ValueError, match="requires an image"):
            OmpAgent._from_config(
                config=config,
                model=model_def,
                credential=credential,
                problem_name="p",
                verbose=False,
                image=None,
                thinking_preset="low",
            )


class TestCommand:
    def test_command_is_vanilla_headless(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        command = agent._build_command("solve it")
        assert command[0] == "omp"
        assert command[1:4] == ["--print", "--mode", "json"]
        for flag in ("--no-extensions", "--no-skills", "--no-rules"):
            assert flag in command
        assert "--advisor" not in command
        assert command[command.index("--model") + 1] == (
            "openai-codex/gpt-6-luna:low"
        )
        assert command[-1] == "solve it"

    def test_shell_command_refreshes_catalog_before_agent(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        prompt = "fix it; don't `rm` $HOME && exit"
        refresh, agent_part = agent._build_shell_command(prompt).split(
            " && ", 1
        )
        assert refresh == "omp models refresh > /dev/null"
        assert shlex.split(agent_part) == agent._build_command(prompt)

    def test_broker_env_present_and_token_not_in_command(
        self,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        env = agent._build_env()
        assert env[BROKER_URL_ENV] == "http://host.docker.internal:8765"
        assert env[BROKER_TOKEN_ENV] == TOKEN
        assert env["PI_CONFIG_DIR"] == ".omp-scb"
        assert TOKEN not in " ".join(agent._build_command("go"))
        assert "agent.db" not in json.dumps(env)

    def test_protected_extra_args_rejected(
        self,
        cost_limits: AgentCostLimits,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        cfg = OmpConfig(
            type="omp",
            version="18.4.4",
            extra_args=["--advisor"],
            cost_limits=cost_limits,
        )
        agent = _make_agent(cfg, model_def, credential, thinking_preset="low")
        with pytest.raises(AgentError, match="protected OMP flag"):
            agent._build_command("go")


class TestParseLine:
    def test_real_message_end_usage_and_cost(self) -> None:
        cost, tokens, payload = OmpAgent.parse_line(REAL_MESSAGE_END)
        assert cost == pytest.approx(0.0008663)
        assert tokens is not None
        assert (tokens.input, tokens.output, tokens.cache_read) == (8638, 5, 0)
        assert payload is not None
        assert payload["message"]["model"] == "gpt-6-luna"

    def test_non_message_end_has_no_usage(self) -> None:
        cost, tokens, payload = OmpAgent.parse_line('{"type":"agent_start"}')
        assert (cost, tokens) == (None, None)
        assert payload == {"type": "agent_start"}


class TestRun:
    def _setup(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
        stdout: str,
        exit_code: int = 0,
    ) -> tuple[OmpAgent, FakeRuntime, FakeSession]:
        runtime = FakeRuntime()
        runtime.events = [
            RuntimeEvent(kind="stdout", text=stdout),
            _finished(stdout, exit_code),
        ]
        session = FakeSession(
            runtime=runtime,
            working_dir=tmp_path,
            spec=DockerEnvironmentSpec(
                name="docker-test", docker=DockerConfig(image="omp-test")
            ),
        )
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        agent.setup(cast("Session", session))
        return agent, runtime, session

    def test_run_records_usage_and_artifacts(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        delta = json.dumps({"type": "message_update", "x": 1})
        agent, runtime, session = self._setup(
            tmp_path,
            config,
            model_def,
            credential,
            f'{{"type":"agent_start"}}\n{delta}\n{REAL_MESSAGE_END}\n',
        )
        agent.run("do it")

        assert agent.usage.cost == pytest.approx(0.0008663, abs=1e-6)
        assert agent.usage.net_tokens.input == 8638
        assert agent.usage.steps == 1

        assert runtime.last_stream_args is not None
        command, env, _ = runtime.last_stream_args
        assert TOKEN not in command
        assert env[BROKER_TOKEN_ENV] == TOKEN
        assert session.last_spawn_env_vars is not None
        assert TOKEN not in json.dumps(session.last_spawn_env_vars)
        assert not session.last_spawn_mounts

        out = tmp_path / "artifacts"
        agent.save_artifacts(out)
        saved = (out / "stdout.jsonl").read_text()
        assert TOKEN not in saved
        assert [json.loads(x)["type"] for x in saved.splitlines()] == [
            "agent_start",
            "message_end",
        ]
        assert (out / "stderr.log").read_text() == "warn\n"

    def test_error_stop_reason_raises(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        line = json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "stopReason": "error",
                    "errorMessage": "quota exhausted",
                    "usage": {"input": 1, "output": 0},
                },
            }
        )
        agent, _, _ = self._setup(
            tmp_path, config, model_def, credential, f"{line}\n"
        )
        with pytest.raises(AgentError, match="quota exhausted"):
            agent.run("do it")

    def test_nonzero_exit_raises(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent, _, _ = self._setup(
            tmp_path, config, model_def, credential, "", exit_code=1
        )
        with pytest.raises(AgentError, match="exit code 1"):
            agent.run("do it")

    def test_setup_requires_docker(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        session = FakeSession(runtime=FakeRuntime(), working_dir=tmp_path)
        with pytest.raises(AgentError, match="Docker"):
            agent.setup(cast("Session", session))


class TestOmpParser:
    def _write_stream(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "stdout.jsonl").write_text(
            '{"type":"session","version":3}\n' + REAL_MESSAGE_END + "\n"
        )

    def test_saved_artifacts_carry_marker_and_parse_as_omp(
        self,
        tmp_path: Path,
        config: OmpConfig,
        model_def: ModelDefinition,
        credential: ProviderCredential,
    ) -> None:
        agent = _make_agent(
            config, model_def, credential, thinking_preset="low"
        )
        agent._artifact_payloads = [json.loads(REAL_MESSAGE_END)]
        out = tmp_path / "artifacts"
        agent.save_artifacts(out)

        assert json.loads((out / "agent.json").read_text()) == {
            "agent_type": "omp",
            "version": "18.4.4",
        }
        assert OmpParser().can_parse(out)
        assert not PiParser().can_parse(out)
        assert parse_trajectory(out).agent_type == "omp"

    def test_marked_directory_parses_as_omp(self, tmp_path: Path) -> None:
        self._write_stream(tmp_path)
        (tmp_path / "agent.json").write_text('{"agent_type": "omp"}')

        assert parse_trajectory(tmp_path).agent_type == "omp"

    def test_unmarked_pi_shaped_directory_stays_pi(
        self, tmp_path: Path
    ) -> None:
        self._write_stream(tmp_path)

        assert not OmpParser().can_parse(tmp_path)
        assert parse_trajectory(tmp_path).agent_type == "pi"
