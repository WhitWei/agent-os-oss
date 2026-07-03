"""Tests for the Autonomy Policy enforcement.

Verifies least-privilege guarantees:
- Path access: inside allowed scope, outside denied
- Command allowlisting
- Write quota enforcement
- Session timeout checks
"""

import os
import time
from pathlib import Path

import pytest

from policies.autonomy_policy import AutonomyPolicy, load_policy
from agentos_kernel.exceptions import PolicyViolationError


# ── Fixtures ──

@pytest.fixture
def policy_config_path(tmp_path: Path) -> str:
    """Create a temporary policy config for testing."""
    import yaml

    config = {
        "version": "1.0",
        "description": "Test policy",
        "filesystem": {
            "allowed_paths": [
                str(tmp_path / "workspace/**"),
                "/tmp/test-agent/**",
            ],
            "denied_paths": [
                str(tmp_path / "workspace/.env"),
                "/etc/**",
            ],
        },
        "commands": {
            "mode": "allowlist",
            "allowed": ["ls", "cat", "echo", "pytest", "python3"],
            "denied": [],
        },
        "write_quotas": {
            "max_operations_per_session": 5,
            "max_operations_per_minute": 3,
            "shacl_required_domains": ["it-asset-mgmt"],
        },
        "network": {
            "allowed_hosts": ["localhost:7687"],
            "default_policy": "deny",
        },
        "session": {
            "max_duration_seconds": 3600,
            "max_token_budget_usd": 0.50,
        },
    }
    config_path = tmp_path / "test_policy.yaml"
    config_path.write_text(yaml.dump(config), encoding="utf-8")
    return str(config_path)


@pytest.fixture
def policy(policy_config_path: str) -> AutonomyPolicy:
    """Create a loaded AutonomyPolicy for testing."""
    return AutonomyPolicy(policy_config_path)


class TestAutonomyPolicyLoading:
    """Verify policy loading and validation."""

    def test_policy_loaded_with_correct_values(self, policy):
        """Policy should load and expose its configuration."""
        status = policy.get_status()
        assert status["version"] == "1.0"
        assert len(status["allowed_commands"]) == 5
        assert "ls" in status["allowed_commands"]

    def test_load_nonexistent_file_raises(self):
        """Loading a nonexistent policy file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            AutonomyPolicy("/nonexistent/policy.yaml")

    def test_load_project_policy(self):
        """The project's actual policy_config.yaml should be loadable."""
        policy_path = Path(__file__).parent.parent / "src" / "policies" / "policy_config.yaml"
        if policy_path.exists():
            p = AutonomyPolicy(str(policy_path))
            assert p.get_status()["version"] == "1.0"


class TestFilesystemChecks:
    """Path access enforcement."""

    def test_allowed_path_within_scope(self, policy, tmp_path: Path):
        """A path matching an allowed pattern should be permitted."""
        workspace = tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
        test_file = workspace / "test.txt"
        test_file.write_text("hello")

        # Should not raise
        policy.check_path_access(str(test_file), "read")

    def test_denied_path_blocked(self, policy, tmp_path: Path):
        """A path matching a denied pattern should be blocked."""
        # /etc/** is denied
        with pytest.raises(PolicyViolationError) as exc:
            policy.check_path_access("/etc/passwd", "read")
        assert "DENIED" in str(exc.value) or "denied" in str(exc.value).lower()

    def test_outside_allowed_scope_blocked(self, policy):
        """A path outside all allowed patterns should be blocked."""
        with pytest.raises(PolicyViolationError) as exc:
            policy.check_path_access("/var/log/system.log", "read")
        assert "outside" in str(exc.value).lower()

    def test_workspace_env_file_blocked(self, policy, tmp_path: Path):
        """The .env file within workspace should be denied via denied_paths."""
        workspace = tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)

        # Create .env (denied)
        env_file = workspace / ".env"
        env_file.write_text("SECRET=test")

        with pytest.raises(PolicyViolationError):
            policy.check_path_access(str(env_file), "read")


class TestCommandChecks:
    """Command allowlist enforcement."""

    def test_allowed_command_passes(self, policy):
        """A command in the allowlist should pass."""
        policy.check_command("ls -la")  # Should not raise

    def test_blocked_command_raises(self, policy):
        """A command not in the allowlist should raise."""
        with pytest.raises(PolicyViolationError) as exc:
            policy.check_command("rm -rf /etc")
        assert "rm" in str(exc.value) or "not in the allowlist" in str(exc.value).lower()

    def test_empty_command(self, policy):
        """Empty command should not crash."""
        # Empty command — should not raise since no program name was extracted
        try:
            policy.check_command("")
        except PolicyViolationError:
            pass  # Also acceptable: empty string not in allowlist

    def test_allowed_commands_list(self, policy):
        """Multiple allowed commands should pass."""
        for cmd in ["ls", "cat file.txt", "echo hello", "pytest -v", "python3 script.py"]:
            policy.check_command(cmd)  # Should not raise


class TestWriteQuotaChecks:
    """Write quota and rate limiting."""

    def test_within_quota_passes(self, policy):
        """First few writes should be within quota."""
        for _ in range(3):
            policy.check_write_quota("it-asset-mgmt")  # Should not raise

        status = policy.get_status()
        assert status["write_count"] == 3

    def test_session_quota_exceeded(self, policy):
        """Exceeding max_operations_per_session should raise (rate limit or quota)."""
        with pytest.raises(PolicyViolationError) as exc:
            for _ in range(10):  # Max is 5 session, 3/min
                policy.check_write_quota("it-asset-mgmt")
        error_msg = str(exc.value).lower()
        assert "quota" in error_msg or "rate" in error_msg or "limit" in error_msg

    def test_shacl_required_domain_logged(self, policy):
        """SHACL-required domain writes are tracked."""
        policy.check_write_quota("it-asset-mgmt")  # Should not raise
        status = policy.get_status()
        assert status["write_count"] == 1


class TestSessionChecks:
    """Session limits enforcement."""

    def test_fresh_session_is_alive(self, policy):
        """A newly loaded policy has an active session."""
        policy.check_session_alive()  # Should not raise
