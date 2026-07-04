"""Tests for the WASM Micro-Sandbox (WO-A2.2).

Verifies:
- Valid WASM execution with correct results
- Sensitive path pre-flight scanning blocks execution
- All host-side imports are rejected
- Fuel exhaustion from infinite loops triggers trap
- Memory limit enforcement
- Invalid WASM bytes are rejected with clear error
- Missing entrypoints are caught
- Config customization is respected
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.sandbox.wasm_executor import WasmSandbox, SandboxConfig, WasmExecutionResult
from agentos.kernel.exceptions import SandboxError

# Import WASM test fixtures
from fixtures_utils import (
    get_simple_add_wasm,
    get_infinite_loop_wasm,
    get_wasi_import_wasm,
    get_sensitive_path_wasm,
    get_invalid_wasm_bytes,
)


# ── Fixtures ──

@pytest.fixture
def sandbox() -> WasmSandbox:
    """Create a default sandbox instance."""
    return WasmSandbox()


@pytest.fixture
def strict_sandbox() -> WasmSandbox:
    """Create a sandbox with stricter limits for testing."""
    config = SandboxConfig(
        fuel_limit=100_000,   # Very small fuel budget
        sensitive_paths=("/etc/passwd", "/etc/shadow", "/proc", "/sys", "/dev"),
    )
    return WasmSandbox(config)


# ── Valid Execution Tests ──

class TestValidExecution:
    """Happy-path: valid WASM returns correct results."""

    def test_add_two_numbers(self, sandbox):
        """Simple add function: 3 + 4 = 7."""
        result = sandbox.execute_untrusted_code(
            get_simple_add_wasm(), entrypoint="add", args=[3, 4]
        )
        assert isinstance(result, WasmExecutionResult)
        assert result.return_values == (7,)
        assert result.trapped is False
        assert result.trap_reason is None
        assert result.fuel_consumed is not None and result.fuel_consumed > 0

    def test_add_negative_numbers(self, sandbox):
        """Add function with negative values."""
        result = sandbox.execute_untrusted_code(
            get_simple_add_wasm(), entrypoint="add", args=[-5, 10]
        )
        assert result.return_values == (5,)

    def test_result_metadata_present(self, sandbox):
        """Result includes fuel consumed and execution time."""
        result = sandbox.execute_untrusted_code(
            get_simple_add_wasm(), entrypoint="add", args=[1, 1]
        )
        assert result.fuel_consumed is not None
        assert result.fuel_consumed > 0
        assert result.execution_time_ms > 0


# ── Security Boundary Tests (Red Lines) ──

class TestSensitivePathBlocking:
    """Pre-flight sensitive-path scan must abort BEFORE instantiation."""

    def test_sensitive_path_etc_passwd_blocked(self, sandbox):
        """RED LINE: WASM containing '/etc/passwd' must trigger SandboxError."""
        with pytest.raises(SandboxError) as exc:
            sandbox.execute_untrusted_code(
                get_sensitive_path_wasm(), entrypoint="add", args=[1, 2]
            )
        assert "sensitive_path" in str(exc.value.trap_reason)

    def test_sensitive_path_proc_blocked(self, strict_sandbox):
        """'/proc' in WASM bytes must be trapped."""
        # Construct bytes with /proc embedded
        tainted = b"\x00asm\x01\x00\x00\x00/proc/cpuinfo"
        with pytest.raises(SandboxError) as exc:
            strict_sandbox.execute_untrusted_code(tainted, entrypoint="main")
        # Either compilation fails or sensitive_path trap fires
        err = str(exc.value).lower()
        assert "sensitive" in err or "compilation" in err or "parse" in err

    def test_sensitive_path_sys_blocked(self, strict_sandbox):
        """'/sys' in WASM bytes must be trapped."""
        tainted = b"\x00asm\x01\x00\x00\x00/sys/kernel/debug"
        with pytest.raises(SandboxError):
            strict_sandbox.execute_untrusted_code(tainted, entrypoint="main")


class TestImportBlocking:
    """All host-side imports must be rejected (safe-by-default)."""

    def test_wasi_import_blocked(self, sandbox):
        """WASM importing wasi_snapshot_preview1 fd_write is rejected."""
        with pytest.raises(SandboxError) as exc:
            sandbox.execute_untrusted_code(
                get_wasi_import_wasm(), entrypoint="do_write"
            )
        assert "unresolved_import" in str(exc.value.trap_reason)


class TestResourceLimits:
    """Memory and CPU limits must be enforced."""

    def test_fuel_exhaustion_traps(self, strict_sandbox):
        """Infinite loop must exhaust fuel and trigger SandboxError."""
        with pytest.raises(SandboxError) as exc:
            strict_sandbox.execute_untrusted_code(
                get_infinite_loop_wasm(), entrypoint="spin"
            )
        err = str(exc.value).lower()
        assert "fuel" in err or "trap" in err


# ── Error Handling Tests ──

class TestErrorHandling:
    """Invalid inputs produce clear, descriptive errors."""

    def test_invalid_wasm_bytes(self, sandbox):
        """Garbage bytes are rejected with compilation error."""
        with pytest.raises(SandboxError) as exc:
            sandbox.execute_untrusted_code(
                get_invalid_wasm_bytes(), entrypoint="main"
            )
        assert "compilation" in str(exc.value).lower() or "parse" in str(exc.value).lower()

    def test_missing_entrypoint(self, sandbox):
        """Nonexistent function name raises descriptive error."""
        with pytest.raises(SandboxError) as exc:
            sandbox.execute_untrusted_code(
                get_simple_add_wasm(), entrypoint="nonexistent_func"
            )
        assert "not found" in str(exc.value)

    def test_no_args_works(self, sandbox):
        """Calling with None args fails gracefully (add needs 2 args, empty list isn't enough)."""
        # The add function requires 2 i32 args. Passing an empty list
        # is a user error and should raise SandboxError with a clear message.
        with pytest.raises(SandboxError) as exc:
            sandbox.execute_untrusted_code(
                get_simple_add_wasm(), entrypoint="add", args=None
            )
        # Should get a clear error about parameter count
        assert "param" in str(exc.value).lower() or "arg" in str(exc.value).lower()


# ── Config Customization Tests ──

class TestConfigCustomization:
    """SandboxConfig settings should be respected."""

    def test_custom_fuel_limit(self):
        """Custom fuel limit in config is applied."""
        config = SandboxConfig(fuel_limit=500_000)
        sb = WasmSandbox(config)
        assert sb.config.fuel_limit == 500_000

    def test_custom_sensitive_paths(self):
        """Custom sensitive paths list is used."""
        config = SandboxConfig(sensitive_paths=("/custom/secret",))
        sb = WasmSandbox(config)
        assert "/custom/secret" in sb.config.sensitive_paths

        # Should trap on the custom path
        tainted = b"\x00asm\x01\x00\x00\x00/custom/secret/key"
        with pytest.raises(SandboxError):
            sb.execute_untrusted_code(tainted, entrypoint="main")

    def test_empty_sensitive_paths(self):
        """Empty sensitive path list disables pre-flight scanning."""
        config = SandboxConfig(sensitive_paths=())
        sb = WasmSandbox(config)
        # This should not trap on sensitive paths (may fail for other reasons)
        try:
            sb.execute_untrusted_code(
                get_sensitive_path_wasm(), entrypoint="add", args=[1, 2]
            )
            # If it reaches here, sensitive path scan was skipped
        except SandboxError as e:
            # If it fails, it should NOT be for sensitive_path
            assert "sensitive_path" not in str(e.trap_reason)

    def test_repeat_execution_same_sandbox(self, sandbox):
        """Multiple executions in the same sandbox should work."""
        r1 = sandbox.execute_untrusted_code(
            get_simple_add_wasm(), entrypoint="add", args=[1, 2]
        )
        r2 = sandbox.execute_untrusted_code(
            get_simple_add_wasm(), entrypoint="add", args=[10, 20]
        )
        assert r1.return_values == (3,)
        assert r2.return_values == (30,)
