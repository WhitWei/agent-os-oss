"""L1 Unit tests for the agentos CLI.

These tests mock all external physical dependencies (filesystem writes,
subprocess calls, MCP server) so they run fast and in isolation.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from agentos.cli.cli import _find_loop_engine, main


# ── Fixtures ──


@pytest.fixture
def runner() -> CliRunner:
    """Click test runner isolated from the real filesystem."""
    return CliRunner()


# ── Tests: agentos init ──


class TestInitCommand:
    """agentos init — generate policy_config.yaml."""

    def test_init_creates_file_in_cwd(self, runner: CliRunner):
        """Should create a policy_config.yaml in the current directory."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0
            assert "Generated" in result.output

            path = Path.cwd() / "policy_config.yaml"
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "version:" in content
            assert "filesystem:" in content
            assert "commands:" in content
            assert "write_quotas:" in content

    def test_init_with_custom_output(self, runner: CliRunner):
        """Should respect the --output flag."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["init", "--output", "my_policy.yaml"])
            assert result.exit_code == 0

            path = Path.cwd() / "my_policy.yaml"
            assert path.exists()

    def test_init_refuses_to_overwrite_without_force(self, runner: CliRunner):
        """Should error when target exists and --force is not set."""
        with runner.isolated_filesystem():
            path = Path.cwd() / "policy_config.yaml"
            path.write_text("existing", encoding="utf-8")

            result = runner.invoke(main, ["init"])
            assert result.exit_code == 1
            assert "already exists" in result.output

    def test_init_force_overwrite(self, runner: CliRunner):
        """Should overwrite existing file when --force is set."""
        with runner.isolated_filesystem():
            path = Path.cwd() / "policy_config.yaml"
            path.write_text("old content", encoding="utf-8")

            result = runner.invoke(main, ["init", "--force"])
            assert result.exit_code == 0
            content = path.read_text(encoding="utf-8")
            assert "old content" not in content
            assert "version:" in content


# ── Tests: agentos start-mcp ──


class TestStartMCPCommand:
    """agentos start-mcp — start MCP governance server."""

    def test_start_mcp_port_parsing(self, runner: CliRunner):
        """Should accept --port argument and fail gracefully."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start-mcp", "--port", "9999"])
            assert result.exit_code == 1
            assert "Config file not found" in result.output

    def test_start_mcp_default_port(self, runner: CliRunner):
        """Should use default port 8100 when not specified."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start-mcp"])
            assert result.exit_code == 1
            assert "Config file not found" in result.output

    def test_start_mcp_host_flag(self, runner: CliRunner):
        """Should accept --host argument."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start-mcp", "--host", "127.0.0.1", "--port", "8888"])
            assert result.exit_code == 1
            assert "Config file not found" in result.output

    # ── Pure mock-based happy path (no real deps) ──

    @patch("agentos.governance.mcp_server.GovernanceGateway")
    @patch("agentos.governance.write_gate.WriteGate")
    @patch("agentos.governance.schema_provider.SchemaProvider")
    @patch("agentos.kernel.config.ConfigLoader")
    def test_start_mcp_happy_path(
        self,
        mock_config_loader_cls,
        mock_schema_provider_cls,
        mock_write_gate_cls,
        mock_gateway_cls,
        runner: CliRunner,
    ):
        """Should bootstrap and start the MCP gateway successfully.

        All external dependencies are fully mocked — no real config,
        schema provider, write gate, or gateway is instantiated.
        """
        # Mock ConfigLoader to return a config with proper nested structure
        mock_config = MagicMock()
        mock_config.mcp.host = "0.0.0.0"
        mock_config.mcp.port = 8100
        mock_config.mcp.server_name = "test-gateway"
        mock_config.mcp.transport = "stdio"
        mock_config.mcp.validation.nonce_secret = "test-secret"
        mock_config.mcp.validation.nonce_ttl_seconds = 300
        mock_config.ontology.owl_dir = "/fake/owl"
        mock_config.ontology.shacl_dir = "/fake/shacl"
        mock_config.ontology.domains = []
        mock_config_loader = MagicMock()
        mock_config_loader.load.return_value = mock_config
        mock_config_loader_cls.return_value = mock_config_loader

        # Mock GovernanceGateway instance: simulate Ctrl+C after run starts
        mock_gateway = MagicMock()
        mock_gateway.run.side_effect = KeyboardInterrupt()
        mock_gateway_cls.return_value = mock_gateway

        with runner.isolated_filesystem():
            result = runner.invoke(main, ["start-mcp", "--port", "8100"])

        assert result.exit_code == 0
        assert "ready" in result.output
        assert "MCP server stopped" in result.output

        # Verify the call chain: ConfigLoader → SchemaProvider → WriteGate → GovernanceGateway
        mock_config_loader_cls.assert_called_once()
        mock_schema_provider_cls.assert_called_once_with(
            owl_dir="/fake/owl", shacl_dir="/fake/shacl", domains=[],
        )
        mock_write_gate_cls.assert_called_once_with(
            schema_provider=mock_schema_provider_cls.return_value,
            neo4j_client=None,
            nonce_secret="test-secret",
            nonce_ttl_seconds=300,
        )
        mock_gateway_cls.assert_called_once_with(
            write_gate=mock_write_gate_cls.return_value,
            config=mock_config,
        )
        mock_gateway.run.assert_called_once()


# ── Tests: agentos loop run ──


class TestLoopRunCommand:
    """agentos loop run — GLE subprocess forwarding."""

    def test_loop_run_without_engine(self, runner: CliRunner):
        """Should give friendly error when loop-engine is not on PATH."""
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            result = runner.invoke(main, ["loop", "run", "--task", "test task"])
            assert result.exit_code == 1
            assert "loop-engine not found" in result.output
            assert "pip install agent-os-cli[loop]" in result.output

    def test_loop_run_parses_args(self, runner: CliRunner):
        """Should parse --task and --mode arguments."""
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            result = runner.invoke(main, [
                "loop", "run",
                "--task", "validate schema",
                "--mode", "validate",
            ])
            assert result.exit_code == 1
            assert "loop-engine not found" in result.output

    @patch("agentos.cli.cli._find_loop_engine")
    @patch("agentos.cli.cli.subprocess.run")
    def test_loop_run_happy_path(
        self, mock_subprocess_run, mock_find_engine, runner: CliRunner
    ):
        """Should invoke subprocess when loop-engine is found."""
        mock_find_engine.return_value = "/usr/local/bin/loop-engine"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Task completed successfully\n"
        mock_result.stderr = ""
        mock_subprocess_run.return_value = mock_result

        result = runner.invoke(main, [
            "loop", "run",
            "--task", "validate schema",
            "--mode", "validate",
        ])
        assert result.exit_code == 0
        assert "completed" in result.output

        mock_subprocess_run.assert_called_once_with(
            ["/usr/local/bin/loop-engine", "--task", "validate schema", "--mode", "validate"],
            capture_output=True,
            text=True,
            timeout=300,
        )

    @patch("agentos.cli.cli._find_loop_engine")
    @patch("agentos.cli.cli.subprocess.run")
    def test_loop_run_failure_exit_code(
        self, mock_subprocess_run, mock_find_engine, runner: CliRunner
    ):
        """Should propagate non-zero exit code from loop-engine."""
        mock_find_engine.return_value = "/usr/local/bin/loop-engine"
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Validation failed\n"
        mock_subprocess_run.return_value = mock_result

        result = runner.invoke(main, [
            "loop", "run",
            "--task", "bad task",
        ])
        assert result.exit_code == 1
        assert "failed with exit code 1" in result.output

    @patch("agentos.cli.cli._find_loop_engine")
    @patch("agentos.cli.cli.subprocess.run")
    def test_loop_run_timeout(
        self, mock_subprocess_run, mock_find_engine, runner: CliRunner
    ):
        """Should handle subprocess timeout gracefully."""
        from subprocess import TimeoutExpired
        mock_find_engine.return_value = "/usr/local/bin/loop-engine"
        mock_subprocess_run.side_effect = TimeoutExpired(cmd="loop-engine", timeout=300)

        result = runner.invoke(main, [
            "loop", "run",
            "--task", "slow task",
        ])
        assert result.exit_code == 1
        assert "timed out" in result.output


# ── Tests: helper ──


class TestFindLoopEngine:
    """_find_loop_engine — PATH scanning helper."""

    def test_no_path_returns_none(self):
        """Empty PATH should return None."""
        with patch.dict(os.environ, {"PATH": ""}, clear=True):
            assert _find_loop_engine() is None

    def test_not_found_returns_none(self, tmp_path: Path):
        """PATH with no loop-engine should return None."""
        with patch.dict(os.environ, {"PATH": str(tmp_path)}, clear=True):
            assert _find_loop_engine() is None


# ── Tests: CLI top-level ──


class TestCliTopLevel:
    """agentos top-level commands."""

    def test_help(self, runner: CliRunner):
        """--help should list all commands."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "start-mcp" in result.output
        assert "loop" in result.output

    def test_version(self, runner: CliRunner):
        """--version should display version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.1" in result.output

    def test_verbose_flag(self, runner: CliRunner):
        """-v should not crash."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["-v", "init"])
            assert result.exit_code == 0
