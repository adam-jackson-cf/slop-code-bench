"""OMP (oh-my-pi) CLI agent implementation.

OMP runs headless inside the Docker environment. Credentials never enter the
container: the operator runs ``omp auth-broker serve`` on the host and the
container only receives the broker URL and its bearer token. The broker hands
out redacted snapshots and performs OAuth refreshes on the host.
"""

from __future__ import annotations

import functools
import json
import shlex
import typing as tp
from pathlib import Path

from jinja2 import Template
from pydantic import Field

from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.agent_runner.agents.pi.agent import PiAgent
from slop_code.agent_runner.agents.provenance import write_marker
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime

OmpThinking = tp.Literal["low", "medium", "high", "xhigh"]

BROKER_PROVIDER = "omp_broker"
DEFAULT_BROKER_URL = "http://host.docker.internal:8765"
BROKER_URL_ENV = "OMP_AUTH_BROKER_URL"
BROKER_TOKEN_ENV = "OMP_AUTH_BROKER_TOKEN"  # noqa: S105
OMP_CONFIG_DIRNAME = ".omp-scb"

_THINKING_PRESETS: dict[str, OmpThinking] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
}

# Vanilla, deterministic runs: no extension/skill/rule discovery, no title
# generation, no advisor (opt-in via ``--advisor``, never passed), and no
# approval prompts that would block a headless run.
_FIXED_FLAGS = (
    "--no-session",
    "--no-extensions",
    "--no-skills",
    "--no-rules",
    "--no-title",
    "--approval-mode=yolo",
)

_FIXED_ENV = {
    "HOME": HOME_PATH,
    "PI_CONFIG_DIR": OMP_CONFIG_DIRNAME,
    "PI_AUTO_QA": "0",
}

_PROTECTED_OMP_FLAGS = (
    "--print",
    "-p",
    "--mode",
    "--no-session",
    "--session",
    "--session-dir",
    "--continue",
    "-c",
    "--resume",
    "-r",
    "--provider",
    "--model",
    "--thinking",
    "--api-key",
    "--advisor",
    "--extension",
    "-e",
    "--hook",
    "--profile",
    "--config",
    "--approval-mode",
    "--auto-approve",
)

_SIGTERM_EXIT_CODE = 128 + 15
_ARTIFACT_EXCLUDED_EVENT_TYPES = frozenset({"message_update"})


class OmpConfig(AgentConfigBase):
    """Configuration for ``OmpAgent`` instances."""

    type: tp.Literal["omp"] = "omp"
    binary: str = "omp"
    version: str
    timeout: int | None = None
    extra_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    broker_url: str = DEFAULT_BROKER_URL
    provider: str | None = None
    thinking: OmpThinking | None = None
    docker_template: Path = Path(__file__).parent / "docker.j2"

    def get_docker_file(self, base_image: str) -> str | None:
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image,
            version=self.version,
        )


class OmpAgent(Agent):
    """Agent implementation built on top of the OMP CLI."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"

    # OMP's message_end usage schema matches Pi's.
    parse_line = staticmethod(PiAgent.parse_line)

    def __init__(
        self,
        problem_name: str,
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential,
        binary: str,
        model_selector: str,
        broker_url: str,
        timeout: int | None,
        extra_args: list[str],
        env: dict[str, str],
        *,
        verbose: bool,
        image: str,
        version: str,
    ) -> None:
        super().__init__(
            agent_name="omp",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )
        self.credential = credential
        self.binary = binary
        self.model_selector = model_selector
        self.broker_url = broker_url
        self.timeout = timeout
        self.extra_args = extra_args
        self.env = env
        self.version = version

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None
        self._artifact_payloads: list[dict[str, tp.Any]] = []

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        *,
        verbose: bool,
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        if not isinstance(config, OmpConfig):
            raise TypeError(f"Expected OmpConfig, got {type(config).__name__}")
        if image is None:
            raise ValueError("OmpAgent requires an image")
        if (
            credential.provider != BROKER_PROVIDER
            or credential.credential_type != CredentialType.FILE
        ):
            raise ValueError(
                "OmpAgent authenticates through the OMP auth broker. Use "
                f"--model {BROKER_PROVIDER}/<model> (got provider "
                f"'{credential.provider}')."
            )
        if not credential.value.strip():
            raise ValueError(
                f"Credential '{BROKER_PROVIDER}' is empty; run "
                "`omp auth-broker serve` once to create the token file."
            )

        omp_provider, model_id = cls._resolve_provider_and_model(
            config=config, model=model
        )
        effort = cls._resolve_effort(
            config_thinking=config.thinking,
            thinking_preset=thinking_preset,
            thinking_max_tokens=thinking_max_tokens,
            model_name=model.internal_name,
        )

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            model_selector=f"{omp_provider}/{model_id}:{effort}",
            broker_url=config.broker_url,
            timeout=config.timeout,
            extra_args=config.extra_args,
            env=config.env,
            version=config.version,
        )

    @staticmethod
    def _resolve_provider_and_model(
        config: OmpConfig,
        model: ModelDefinition,
    ) -> tuple[str, str]:
        settings = model.get_agent_settings("omp") or {}
        provider = config.provider or settings.get("provider")
        if not isinstance(provider, str) or not provider:
            raise ValueError(
                f"Model '{model.internal_name}' has no OMP provider. Add "
                "agent_specific.omp.provider to its model config or set "
                "`provider` in the agent config."
            )
        model_id = settings.get("model") or model.get_model_slug(provider)
        return provider, str(model_id)

    @staticmethod
    def _resolve_effort(
        config_thinking: OmpThinking | None,
        thinking_preset: ThinkingPreset | None,
        thinking_max_tokens: int | None,
        model_name: str,
    ) -> OmpThinking:
        if config_thinking is not None:
            return config_thinking
        if thinking_max_tokens is not None:
            raise ValueError(
                "OMP does not support token-budget thinking; use a preset "
                "(low|medium|high|xhigh)."
            )
        effort = _THINKING_PRESETS.get(thinking_preset or "")
        if effort is None:
            raise ValueError(
                f"OMP requires an explicit reasoning effort for "
                f"'{model_name}' (low|medium|high|xhigh); got "
                f"thinking={thinking_preset!r}. Models served through OMP "
                "have no off mode: 'none'/'disabled' would silently fall "
                "back to the provider default, so they are rejected."
            )
        return effort

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("OmpAgent has not been set up with a session")
        return self._session

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("OmpAgent has not been set up with a runtime")
        return self._runtime

    def setup(self, session: Session) -> None:
        if not isinstance(session.spec, DockerEnvironmentSpec):
            raise AgentError(
                "OmpAgent requires a Docker environment; the broker URL is "
                "resolved from inside the container."
            )
        self._session = session
        self._environment = session.spec
        self._artifact_payloads = []
        self._runtime = session.spawn(
            env_vars=dict(_FIXED_ENV),
            image=self._image,
            user="agent",
            disable_setup=True,
        )

    def run(self, task: str) -> None:
        self._last_prompt = task
        self._last_command = None
        self._artifact_payloads = []

        self.log.info(
            "agent.omp.start",
            workspace=str(self.session.working_dir),
            prompt_chars=len(task),
            model=self.model_selector,
            broker_url=self.broker_url,
            image=self._image,
            extra_args=self.extra_args,
        )

        command_result = self._run_invocation(task)
        self._last_command = command_result
        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            message = "OMP process failed to start"
            self.log.error(
                "agent.omp.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
            )
            raise AgentError(message)

        if runtime_result.timed_out:
            message = (
                f"OMP process timed out after {self.timeout}s."
                if self.timeout is not None
                else "OMP process timed out."
            )
            self.log.error("agent.omp.timeout", error_message=message)
            raise AgentError(message)

        if runtime_result.exit_code == _SIGTERM_EXIT_CODE:
            self.log.warning(
                "agent.omp.sigterm", exit_code=runtime_result.exit_code
            )
        elif runtime_result.exit_code != 0:
            message = (
                f"OMP process failed with exit code {runtime_result.exit_code}"
            )
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.omp.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

        if command_result.had_error:
            message = (
                command_result.error_message
                or "OMP returned an error event in structured output."
            )
            self.log.error("agent.omp.message_error", error_message=message)
            raise AgentError(message)

    def _run_invocation(self, task: str) -> AgentCommandResult:
        command = self._build_shell_command(task)
        env_overrides = self._build_env()

        parser = tp.cast(
            "tp.Callable[[str], tuple[float | None, TokenUsage | None, dict]]",
            functools.partial(self.parse_line, pricing=self.pricing),
        )

        total_tokens = TokenUsage()
        step_count = 0
        runtime_result = None
        reported_cost_micros = 0
        has_reported_cost = False
        stream_error_message: str | None = None

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command,
            parser=parser,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        ):
            if not isinstance(item, tuple):
                runtime_result = item
                break

            _, tokens, payload = item
            if tokens is not None:
                total_tokens = total_tokens + tokens
            if not payload:
                continue

            event_type = payload.get("type")
            if event_type not in _ARTIFACT_EXCLUDED_EVENT_TYPES:
                self._artifact_payloads.append(payload)

            if event_type == "message_end":
                message = payload.get("message")
                if (
                    isinstance(message, dict)
                    and message.get("role") == "assistant"
                ):
                    step_count += 1
                    self.usage.steps += 1
                    stop_reason = message.get("stopReason")
                    if stop_reason in {"error", "aborted"}:
                        error_message = message.get("errorMessage")
                        stream_error_message = (
                            error_message
                            if isinstance(error_message, str) and error_message
                            else (
                                "OMP assistant message ended with "
                                f"stopReason='{stop_reason}'."
                            )
                        )
                    usage = message.get("usage")
                    usage_cost = (
                        usage.get("cost") if isinstance(usage, dict) else None
                    )
                    if isinstance(usage_cost, dict):
                        total = usage_cost.get("total")
                        if isinstance(total, int | float):
                            has_reported_cost = True
                            reported_cost_micros += round(
                                float(total) * 1_000_000
                            )
            elif event_type == "tool_execution_end":
                step_count += 1
                self.usage.steps += 1

        return AgentCommandResult(
            result=runtime_result,
            steps=[],
            usage_totals={
                "input_tokens": total_tokens.input,
                "output_tokens": total_tokens.output,
                "cached_input_tokens": total_tokens.cache_read,
                "cached_write_tokens": total_tokens.cache_write,
                "reasoning_tokens": total_tokens.reasoning,
                "total_tokens": total_tokens.input + total_tokens.output,
                "steps": step_count,
                "reported_cost_present": int(has_reported_cost),
                "reported_cost_micros": reported_cost_micros,
            },
            stdout=runtime_result.stdout if runtime_result else "",
            stderr=runtime_result.stderr if runtime_result else "",
            had_error=stream_error_message is not None,
            error_message=stream_error_message,
        )

    def _build_env(self) -> dict[str, str]:
        env = {key: str(value) for key, value in self.env.items()}
        env.update(_FIXED_ENV)
        env[BROKER_URL_ENV] = self.broker_url
        env[BROKER_TOKEN_ENV] = self.credential.value.strip()
        return env

    def _build_command(self, prompt: str) -> list[str]:
        self._validate_extra_args()
        return [
            self.binary,
            "--print",
            "--mode",
            "json",
            *_FIXED_FLAGS,
            "--model",
            self.model_selector,
            *self.extra_args,
            prompt,
        ]

    def _build_shell_command(self, prompt: str) -> str:
        """Return the ``/bin/sh -c`` command for one agent invocation.

        A fresh container has no model cache, and some Codex models (for
        example ``gpt-6.1-sol``) exist only in live provider discovery, so
        ``omp --print`` would report them as not found. Refresh the catalog
        through the broker first; a failed refresh fails the invocation.
        Refresh output is discarded so only agent JSON reaches the parser.
        """
        refresh = shlex.join([self.binary, "models", "refresh"])
        agent = shlex.join(self._build_command(prompt))
        return f"{refresh} > /dev/null && {agent}"

    def _validate_extra_args(self) -> None:
        for arg in self.extra_args:
            if any(
                arg == protected or arg.startswith(f"{protected}=")
                for protected in _PROTECTED_OMP_FLAGS
            ):
                raise AgentError(
                    f"extra_args contains protected OMP flag '{arg}'. "
                    "Configure required OMP flags via OmpConfig fields."
                )

    def _sync_usage(self, totals: dict[str, int]) -> None:
        totals = totals or {}
        tokens = TokenUsage(
            input=int(totals.get("input_tokens") or 0),
            output=int(totals.get("output_tokens") or 0),
            cache_read=int(totals.get("cached_input_tokens") or 0),
            cache_write=int(totals.get("cached_write_tokens") or 0),
            reasoning=int(totals.get("reasoning_tokens") or 0),
        )

        if int(totals.get("reported_cost_present") or 0):
            cost = (
                float(int(totals.get("reported_cost_micros") or 0)) / 1_000_000
            )
        else:
            cost = self.pricing.get_cost(tokens) if self.pricing else 0.0

        self.usage.cost += cost
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("OmpAgent exceeded configured usage limits")

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        artifact_payloads: list[dict[str, tp.Any]],
        stderr_text: str,
    ) -> None:
        with (output_dir / cls.STDOUT_FILENAME).open("w") as handle:
            for payload in artifact_payloads:
                handle.write(json.dumps(payload, separators=(",", ":")))
                handle.write("\n")
        (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        self._last_prompt = ""
        self._last_command = None
        self._artifact_payloads = []

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stderr_text = ""
        if self._last_command is not None:
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, self._artifact_payloads, stderr_text)
        write_marker(path, "omp", self.version)

    def cleanup(self) -> None:
        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None
        self._session = None
        self._environment = None


register_agent("omp", OmpAgent)
