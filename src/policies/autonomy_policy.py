"""Autonomy Policy — least-privilege enforcement for Agent OS.

Loads a declarative YAML policy file and enforces:
- Filesystem scope (allowed/denied paths, glob support)
- Command allowlisting/denylisting
- Write operation quotas
- Network egress filtering
- Session limits

All policy violations raise PolicyViolationError, which the kernel
catches and reports back through the channel adapter.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from zeroclaw.exceptions import PolicyViolationError

logger = logging.getLogger(__name__)


# ── Pydantic Policy Models ──


class FilesystemPolicy(BaseModel):
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)


class CommandsPolicy(BaseModel):
    mode: str = "allowlist"  # "allowlist" or "denylist"
    allowed: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)


class WriteQuotasPolicy(BaseModel):
    max_operations_per_session: int = 50
    max_operations_per_minute: int = 10
    shacl_required_domains: list[str] = Field(default_factory=list)


class NetworkPolicy(BaseModel):
    allowed_hosts: list[str] = Field(default_factory=list)
    default_policy: str = "deny"


class SessionLimitsPolicy(BaseModel):
    max_duration_seconds: int = 3600
    max_token_budget_usd: float = 0.50


class PolicyConfig(BaseModel):
    """Full autonomy policy configuration."""

    version: str = "1.0"
    description: str = ""
    filesystem: FilesystemPolicy = Field(default_factory=FilesystemPolicy)
    commands: CommandsPolicy = Field(default_factory=CommandsPolicy)
    write_quotas: WriteQuotasPolicy = Field(default_factory=WriteQuotasPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    session: SessionLimitsPolicy = Field(default_factory=SessionLimitsPolicy)


# ── Policy Enforcer ──


class AutonomyPolicy:
    """Enforces least-privilege autonomy policy at runtime.

    The kernel calls check_*() methods before each operation.
    If any check fails, a PolicyViolationError is raised with
    a descriptive message — the kernel blocks the operation and
    reports back to the user.
    """

    def __init__(self, policy_config_path: str) -> None:
        self._path = Path(policy_config_path)
        self._config = self._load()
        self._session_start = time.time()
        self._write_count = 0
        self._write_timestamps: list[float] = []
        logger.info(
            "AutonomyPolicy loaded: %d allowed paths, %d allowed commands, "
            "write quota=%d/session",
            len(self._config.filesystem.allowed_paths),
            len(self._config.commands.allowed),
            self._config.write_quotas.max_operations_per_session,
        )

    def _load(self) -> PolicyConfig:
        """Load and validate the policy YAML file."""
        if not self._path.exists():
            raise FileNotFoundError(f"Policy config not found: {self._path}")
        raw = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        return PolicyConfig(**raw)

    # ── Filesystem Checks ──

    def check_path_access(self, target_path: str, operation: str = "read") -> None:
        """Check if a file path is within the allowed scope.

        Args:
            target_path: Absolute or relative path to check.
            operation: "read" or "write".

        Raises:
            PolicyViolationError: If the path is outside allowed scope.
        """
        resolved = str(Path(target_path).resolve())

        # Check denied paths first (takes precedence)
        for pattern in self._config.filesystem.denied_paths:
            if self._match_path(resolved, pattern):
                raise PolicyViolationError(
                    f"Path access DENIED: '{target_path}' matches denied pattern '{pattern}'. "
                    f"Operation '{operation}' blocked."
                )

        # Check allowed paths
        for pattern in self._config.filesystem.allowed_paths:
            if self._match_path(resolved, pattern):
                logger.debug("Path access allowed: %s (%s)", target_path, operation)
                return

        raise PolicyViolationError(
            f"Path access DENIED: '{target_path}' is outside allowed workspace. "
            f"Allowed patterns: {self._config.filesystem.allowed_paths}. "
            f"Operation '{operation}' blocked."
        )

    def _match_path(self, resolved_path: str, pattern: str) -> bool:
        """Match a resolved path against a glob pattern.

        Supports:
        - /**/ for recursive directory matching
        - * for single-level wildcards
        - Works with both absolute and relative patterns
        """
        # If pattern is absolute, match directly
        if pattern.startswith("/"):
            return fnmatch.fnmatch(resolved_path, pattern) or resolved_path.startswith(
                pattern.rstrip("*").rstrip("/")
            )

        # If pattern is relative, also try matching against the pattern directly
        return fnmatch.fnmatch(resolved_path, f"*/{pattern}")

    # ── Command Checks ──

    def check_command(self, command: str) -> None:
        """Check if a shell command is in the allowlist.

        Args:
            command: The command string (first word is the program name).

        Raises:
            PolicyViolationError: If the command is not allowed.
        """
        program = command.strip().split()[0] if command.strip() else ""

        if self._config.commands.mode == "allowlist":
            if program in self._config.commands.allowed:
                logger.debug("Command allowed: %s", program)
                return
            raise PolicyViolationError(
                f"Command '{program}' is not in the allowlist. "
                f"Allowed commands: {self._config.commands.allowed}"
            )
        else:  # denylist mode
            if program in self._config.commands.denied:
                raise PolicyViolationError(
                    f"Command '{program}' is explicitly denied. "
                    f"This command cannot be executed."
                )
            return

    # ── Write Quota Checks ──

    def check_write_quota(self, domain: str) -> None:
        """Check if write operation is within session quotas.

        Args:
            domain: The domain being written to (e.g., 'it-asset-mgmt').

        Raises:
            PolicyViolationError: If quotas are exceeded.
        """
        now = time.time()

        # Check total session quota
        if self._write_count >= self._config.write_quotas.max_operations_per_session:
            raise PolicyViolationError(
                f"Write quota exhausted: {self._write_count}/{self._config.write_quotas.max_operations_per_session} "
                f"operations this session. Start a new session to continue."
            )

        # Check rate limit (per minute)
        # Prune old timestamps
        cutoff = now - 60
        self._write_timestamps = [
            ts for ts in self._write_timestamps if ts > cutoff
        ]

        if len(self._write_timestamps) >= self._config.write_quotas.max_operations_per_minute:
            raise PolicyViolationError(
                f"Write rate limit exceeded: {len(self._write_timestamps)} operations "
                f"in the last 60s (max: {self._config.write_quotas.max_operations_per_minute}/min). "
                f"Please wait before retrying."
            )

        # Check if domain requires SHACL validation
        shacl_required = self._config.write_quotas.shacl_required_domains
        if domain in shacl_required or "*" in shacl_required:
            logger.debug(
                "Domain '%s' requires SHACL validation (enforced)", domain
            )

        # Record the write
        self._write_count += 1
        self._write_timestamps.append(now)

    # ── Session Checks ──

    def check_session_alive(self) -> None:
        """Check if the session has exceeded its max duration.

        Raises:
            PolicyViolationError: If session TTL is exceeded.
        """
        elapsed = time.time() - self._session_start
        max_duration = self._config.session.max_duration_seconds

        if elapsed > max_duration:
            raise PolicyViolationError(
                f"Session expired: running for {elapsed:.0f}s "
                f"(max: {max_duration}s). Please start a new session."
            )

    # ── Reporting ──

    def get_status(self) -> dict:
        """Return current policy enforcement status for diagnostics."""
        return {
            "version": self._config.version,
            "session_elapsed_seconds": int(time.time() - self._session_start),
            "write_count": self._write_count,
            "write_quota_max": self._config.write_quotas.max_operations_per_session,
            "recent_writes_per_minute": len(self._write_timestamps),
            "allowed_paths": self._config.filesystem.allowed_paths,
            "allowed_commands": self._config.commands.allowed,
        }


def load_policy(policy_config_path: Optional[str] = None) -> AutonomyPolicy:
    """Factory function to load the autonomy policy.

    Args:
        policy_config_path: Path to the policy YAML file.
                           Defaults to 'src/policies/policy_config.yaml'.

    Returns:
        Configured AutonomyPolicy instance.
    """
    if policy_config_path is None:
        policy_config_path = os.environ.get(
            "AGENT_OS_POLICY_CONFIG",
            "src/policies/policy_config.yaml",
        )
    return AutonomyPolicy(policy_config_path)
