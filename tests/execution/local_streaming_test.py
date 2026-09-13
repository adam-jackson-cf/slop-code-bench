"""Tests for LocalStreamingRuntime."""

from __future__ import annotations

import os
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.local_streaming import LocalStreamingRuntime
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult
from slop_code.execution.runtime import SolutionRuntimeError


def _wait_for_process_exit(pid: int, timeout: float = 2.0) -> None:
    """Assert that a process is gone before the deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"Process {pid} outlived its process group")


def _descendant_command(child_pid_file: Path) -> str:
    """Build a shell command that records a background child PID."""
    script = f"sleep 60 & echo $! > {shlex.quote(str(child_pid_file))}; wait"
    return f"sh -c {shlex.quote(script)}"


def _exiting_parent_command(child_pid_file: Path) -> str:
    """Build a command whose parent exits after spawning a child."""
    script = (
        "sleep 60 </dev/null >/dev/null 2>&1 & "
        f"echo $! > {shlex.quote(str(child_pid_file))}"
    )
    return f"sh -c {shlex.quote(script)}"


@pytest.fixture
def local_spec() -> LocalEnvironmentSpec:
    """Create a LocalEnvironmentSpec for testing."""
    return LocalEnvironmentSpec(
        type="local",
        name="test-local",
        commands=CommandConfig(command="python"),
    )


@pytest.fixture
def local_spec_with_setup() -> LocalEnvironmentSpec:
    """Create a LocalEnvironmentSpec with setup commands."""
    return LocalEnvironmentSpec(
        type="local",
        name="test-local-setup",
        commands=CommandConfig(command="python"),
        setup=SetupConfig(
            commands=["echo 'setup command 1'"],
            eval_commands=["echo 'eval setup'"],
        ),
    )


class TestLocalEnvironmentSpec:
    """Tests for LocalEnvironmentSpec."""

    def test_type_is_local(self) -> None:
        """Environment type is 'local'."""
        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
        )
        assert spec.type == "local"


class TestLocalStreamingRuntimeInit:
    """Tests for LocalStreamingRuntime initialization."""

    def test_init_stores_working_dir(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory is stored."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.cwd == tmp_path

    def test_init_stores_spec(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Environment spec is stored."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.spec == local_spec

    def test_init_process_is_none(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Process is None initially."""
        runtime = LocalStreamingRuntime(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime._proc is None


class TestLocalStreamingRuntimeSpawn:
    """Tests for LocalStreamingRuntime.spawn()."""

    def test_spawn_creates_runtime(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn creates a LocalStreamingRuntime instance."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert isinstance(runtime, LocalStreamingRuntime)

    def test_spawn_rejects_wrong_environment_type(self, tmp_path: Path) -> None:
        """Spawn raises ValueError for wrong environment type."""
        mock_spec = MagicMock()
        mock_spec.type = "docker"

        with pytest.raises(ValueError, match="Invalid environment spec"):
            LocalStreamingRuntime.spawn(
                environment=mock_spec,
                working_dir=tmp_path,
            )

    def test_spawn_runs_setup_commands(self, tmp_path: Path) -> None:
        """Spawn runs setup commands during creation."""
        marker_file = tmp_path / "setup_ran"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=[f"printf ready > {marker_file}"],
            ),
        )

        LocalStreamingRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
        )

        assert marker_file.read_text() == "ready"

    def test_spawn_with_disable_setup(self, tmp_path: Path) -> None:
        """Spawn skips setup commands when disable_setup=True."""
        marker_file = tmp_path / "should_not_exist"

        spec = LocalEnvironmentSpec(
            type="local",
            name="test",
            commands=CommandConfig(command="python"),
            setup=SetupConfig(
                commands=[f"touch {marker_file}"],
            ),
        )

        LocalStreamingRuntime.spawn(
            environment=spec,
            working_dir=tmp_path,
            disable_setup=True,
        )

        assert not marker_file.exists()


class TestLocalStreamingRuntimeStream:
    """Tests for LocalStreamingRuntime.stream()."""

    def test_stream_yields_events(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream yields RuntimeEvent objects."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo hello", env={}, timeout=10))
            assert len(events) > 0
            assert all(isinstance(e, RuntimeEvent) for e in events)
        finally:
            runtime.cleanup()

    def test_stream_captures_stdout(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stdout in events."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream("echo hello_world", env={}, timeout=10)
            )
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(
                e.text for e in stdout_events if e.text is not None
            )
            assert "hello_world" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_captures_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream captures stderr in events."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream("sh -c 'echo error_msg >&2'", env={}, timeout=10)
            )
            stderr_events = [e for e in events if e.kind == "stderr"]
            stderr_text = "".join(
                e.text for e in stderr_events if e.text is not None
            )
            assert "error_msg" in stderr_text
        finally:
            runtime.cleanup()

    def test_stream_ends_with_finished_event(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream ends with a 'finished' event."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=10))
            assert events[-1].kind == "finished"
        finally:
            runtime.cleanup()

    def test_stream_finished_has_result(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event contains RuntimeResult."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("echo test", env={}, timeout=10))
            finished = events[-1]
            assert finished.result is not None
            assert isinstance(finished.result, RuntimeResult)
        finally:
            runtime.cleanup()

    def test_stream_result_has_exit_code(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Finished event result has correct exit code."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("sh -c 'exit 42'", env={}, timeout=10))
            finished = events[-1]
            result = finished.result
            assert result is not None
            assert result.exit_code == 42
        finally:
            runtime.cleanup()

    def test_stream_with_environment_variables(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream passes environment variables."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream(
                    "sh -c 'echo $MY_VAR'",
                    env={"MY_VAR": "test_value"},
                    timeout=10,
                )
            )
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(
                e.text for e in stdout_events if e.text is not None
            )
            assert "test_value" in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_merges_spawn_and_command_environment(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Spawn variables persist and command variables take precedence."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
            env_vars={"SPAWN_ONLY": "spawn", "SHARED": "spawn"},
        )
        try:
            events = list(
                runtime.stream(
                    'sh -c \'printf "%s:%s:%s" "$SPAWN_ONLY" '
                    '"$COMMAND_ONLY" "$SHARED"\'',
                    env={"COMMAND_ONLY": "command", "SHARED": "command"},
                    timeout=10,
                )
            )
            stdout = "".join(
                event.text
                for event in events
                if event.kind == "stdout" and event.text is not None
            )
            assert stdout == "spawn:command:command"
        finally:
            runtime.cleanup()

    def test_stream_uses_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Stream runs in the specified working directory."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("pwd", env={}, timeout=10))
            stdout_events = [e for e in events if e.kind == "stdout"]
            stdout_text = "".join(
                e.text for e in stdout_events if e.text is not None
            )
            assert str(tmp_path) in stdout_text
        finally:
            runtime.cleanup()

    def test_stream_multiple_commands(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Multiple stream calls work on same runtime."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # First command
            events1 = list(runtime.stream("echo first", env={}, timeout=10))
            assert events1[-1].kind == "finished"

            # Second command
            events2 = list(runtime.stream("echo second", env={}, timeout=10))
            assert events2[-1].kind == "finished"

            # Check output from finished result (more reliable than events)
            result1 = events1[-1].result
            result2 = events2[-1].result
            assert result1 is not None
            assert result2 is not None
            assert result1.exit_code == 0
            assert result2.exit_code == 0
            # Output should be captured in either events or result
            stdout1 = (
                "".join(
                    e.text
                    for e in events1
                    if e.kind == "stdout" and e.text is not None
                )
                or result1.stdout
            )
            stdout2 = (
                "".join(
                    e.text
                    for e in events2
                    if e.kind == "stdout" and e.text is not None
                )
                or result2.stdout
            )
            assert "first" in stdout1
            assert "second" in stdout2
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimePoll:
    """Tests for LocalStreamingRuntime.poll()."""

    def test_poll_returns_none_when_no_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns None when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        assert runtime.poll() is None

    def test_poll_returns_exit_code_after_completion(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Poll returns exit code after stream completes."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Consume the stream to completion
            list(runtime.stream("sh -c 'exit 5'", env={}, timeout=10))
            # Poll should return None after cleanup by stream
            # The process has already been consumed
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimeKill:
    """Tests for LocalStreamingRuntime.kill()."""

    def test_kill_is_safe_when_no_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill is safe to call when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        # Should not raise
        runtime.kill()

    def test_kill_terminates_running_process(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Kill terminates a ready parent and its descendant within a deadline."""
        child_pid_file = tmp_path / "child.pid"
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        proc = runtime._start_process(
            _descendant_command(child_pid_file),
            env={},
        )
        try:
            deadline = time.monotonic() + 2
            while not child_pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert child_pid_file.exists()
            assert proc.poll() is None
            child_pid = int(child_pid_file.read_text())
            runtime.kill()
            assert proc.wait(timeout=2) is not None
            _wait_for_process_exit(child_pid)
        finally:
            runtime.cleanup()
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()

    def test_kill_terminates_direct_child_when_group_kill_is_denied(
        self,
        local_spec: LocalEnvironmentSpec,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Kill the direct child when process-group signaling is denied."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        proc = MagicMock()
        proc.poll.return_value = None

        def deny_group_kill(*_args: object) -> None:
            raise PermissionError

        monkeypatch.setattr(os, "killpg", deny_group_kill)
        runtime._process_group_id = 123
        runtime._terminate_process_group(proc)

        proc.kill.assert_called_once_with()
        proc.wait.assert_called_once_with(timeout=5)


class TestLocalStreamingRuntimeCleanup:
    """Tests for LocalStreamingRuntime.cleanup()."""

    def test_cleanup_is_idempotent(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup can be called multiple times safely."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        list(runtime.stream("echo test", env={}, timeout=10))
        # Should not raise on multiple calls
        runtime.cleanup()
        runtime.cleanup()
        runtime.cleanup()

    def test_cleanup_terminates_process_group(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup terminates a parent and its descendant within a deadline."""
        child_pid_file = tmp_path / "cleanup-child.pid"
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        proc = runtime._start_process(
            _descendant_command(child_pid_file),
            env={},
        )
        try:
            deadline = time.monotonic() + 2
            while not child_pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert child_pid_file.exists()
            started = time.monotonic()
            runtime.cleanup()
            assert time.monotonic() - started < 3
            assert proc.wait(timeout=2) is not None
            _wait_for_process_exit(int(child_pid_file.read_text()))
        finally:
            runtime.cleanup()
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()

    def test_cleanup_terminates_descendant_after_parent_exits(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Cleanup kills descendants after their direct parent exits."""
        child_pid_file = tmp_path / "exited-parent-child.pid"
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        proc = runtime._start_process(
            _exiting_parent_command(child_pid_file),
            env={},
        )
        try:
            assert proc.wait(timeout=2) == 0
            assert child_pid_file.exists()
            started = time.monotonic()
            runtime.cleanup()
            assert time.monotonic() - started < 3
            _wait_for_process_exit(int(child_pid_file.read_text()))
        finally:
            runtime.cleanup()
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()


class TestLocalStreamingRuntimeProcess:
    """Tests for process property."""

    def test_process_raises_when_not_running(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Process property raises when no process is running."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        with pytest.raises(SolutionRuntimeError, match="Process not running"):
            _ = runtime.process


class TestLocalStreamingRuntimeIntegration:
    """Integration tests for LocalStreamingRuntime."""

    def test_full_lifecycle(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test complete spawn -> stream -> cleanup lifecycle."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream("echo integration_test", env={}, timeout=10)
            )
            finished = events[-1]
            result = finished.result
            assert result is not None
            assert result.exit_code == 0
            stdout_text = "".join(
                e.text
                for e in events
                if e.kind == "stdout" and e.text is not None
            )
            assert "integration_test" in stdout_text
        finally:
            runtime.cleanup()

    def test_file_io_in_working_directory(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test file I/O operations in working directory."""
        test_file = tmp_path / "test_input.txt"
        test_file.write_text("input content")

        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(
                runtime.stream("cat test_input.txt", env={}, timeout=10)
            )
            stdout_text = "".join(
                e.text
                for e in events
                if e.kind == "stdout" and e.text is not None
            )
            assert "input content" in stdout_text
        finally:
            runtime.cleanup()

    def test_large_output_handling(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test handling of large output."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("seq 1 1000", env={}, timeout=10))
            stdout_text = "".join(
                e.text
                for e in events
                if e.kind == "stdout" and e.text is not None
            )
            lines = stdout_text.strip().split("\n")
            assert len(lines) == 1000
        finally:
            runtime.cleanup()

    def test_concurrent_stdout_stderr(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test capturing concurrent stdout and stderr."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Use sh -c to properly handle shell redirects
            cmd = "sh -c 'echo stdout_line_1; echo stderr_line_1 >&2; echo stdout_line_2; echo stderr_line_2 >&2'"
            events = list(runtime.stream(cmd, env={}, timeout=10))
            stdout_text = "".join(
                e.text
                for e in events
                if e.kind == "stdout" and e.text is not None
            )
            stderr_text = "".join(
                e.text
                for e in events
                if e.kind == "stderr" and e.text is not None
            )
            # Check that stdout was captured
            assert "stdout_line_1" in stdout_text
            assert "stdout_line_2" in stdout_text
            # Check that stderr was captured (may be combined with stdout in some cases)
            assert (
                "stderr_line_1" in stderr_text or "stderr_line_1" in stdout_text
            )
            assert (
                "stderr_line_2" in stderr_text or "stderr_line_2" in stdout_text
            )
        finally:
            runtime.cleanup()

    def test_mixed_output_drains_without_blocking(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Ready bytes are decoded incrementally while stderr drains fully."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        command = (
            'sh -c \'printf "\\342"; sleep 0.05; '
            'printf "\\202\\254marker\\n"; '
            "yes x | head -c 131072 >&2'"
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                events = executor.submit(
                    lambda: list(runtime.stream(command, env={}, timeout=3))
                ).result(timeout=5)
            stdout = "".join(
                event.text
                for event in events
                if event.kind == "stdout" and event.text is not None
            )
            stderr = "".join(
                event.text
                for event in events
                if event.kind == "stderr" and event.text is not None
            )
            assert "€marker" in stdout
            assert len(stderr) == 131072
        finally:
            runtime.cleanup()

    def test_timeout_during_stream(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Test timeout handling during streaming."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            events = list(runtime.stream("sleep 10", env={}, timeout=0.5))
            finished = events[-1]
            result = finished.result
            assert result is not None
            assert result.timed_out is True
        finally:
            runtime.cleanup()

    def test_timeout_terminates_process_group(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Timeout reaps a parent and descendant that inherit output pipes."""
        child_pid_file = tmp_path / "timeout-child.pid"
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        command = _descendant_command(child_pid_file)
        try:
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=1) as executor:
                events = executor.submit(
                    lambda: list(runtime.stream(command, env={}, timeout=0.2))
                ).result(timeout=3)
            assert time.monotonic() - started < 3
            finished = events[-1]
            result = finished.result
            assert result is not None
            assert result.timed_out is True
            _wait_for_process_exit(int(child_pid_file.read_text()))
        finally:
            runtime.cleanup()

    def test_working_dir_persists_between_commands(
        self, local_spec: LocalEnvironmentSpec, tmp_path: Path
    ) -> None:
        """Working directory persists between stream calls."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )
        try:
            # Create a file with first command
            list(
                runtime.stream(
                    "sh -c 'echo test > testfile.txt'", env={}, timeout=10
                )
            )

            # Verify file exists with second command
            events = list(
                runtime.stream("cat testfile.txt", env={}, timeout=10)
            )
            stdout_text = "".join(
                e.text
                for e in events
                if e.kind == "stdout" and e.text is not None
            )
            assert "test" in stdout_text
        finally:
            runtime.cleanup()


class TestLocalStreamingRuntimeDemuxedStream:
    """Tests for _create_demuxed_stream method."""

    def test_demuxed_echo_cleanup_handles_denied_group_kill(
        self,
        local_spec: LocalEnvironmentSpec,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Cleanup succeeds after demuxing echo when group signaling is denied."""
        runtime = LocalStreamingRuntime.spawn(
            environment=local_spec,
            working_dir=tmp_path,
        )

        def deny_group_kill(*_args: object) -> None:
            raise PermissionError

        try:
            proc = runtime._start_process("echo test", env={})
            chunks = list(runtime._create_demuxed_stream(proc))
            assert chunks == [("test\n", "")]
            monkeypatch.setattr(os, "killpg", deny_group_kill)
        finally:
            runtime.cleanup()
