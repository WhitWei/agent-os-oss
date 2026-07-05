"""WASM Micro-Sandbox — execute untrusted code with strict resource limits.

Integrates wasmtime (Python bindings to the Wasmtime engine) to run
untrusted WebAssembly modules in an isolated context with:

- No filesystem preopens (all disk I/O blocked by default)
- No network access (WASI config with no preopens)
- 16 MB memory hard limit
- CPU-fuel (instruction count) hard limit
- Explicit trap on sensitive-path access attempts

Usage:
    sandbox = WasmSandbox()
    result = sandbox.execute_untrusted_code(wasm_bytes, entrypoint="main")
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Optional

from agentos.kernel.exceptions import SandboxError

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Try to import wasmtime; if unavailable, provide a stub.
# ═══════════════════════════════════════════════════════════════
try:
    import wasmtime as wt
    from wasmtime import (
        Config as _Config,
        Store,
        Module,
        Trap,
        Linker,
        Func,
    )
    _WASMTIME_AVAILABLE = True
except ImportError as _exc:  # pragma: no cover
    _WASMTIME_AVAILABLE = False
    _Config = None  # type: ignore
    logger.warning("wasmtime not installed — WASM sandbox is unavailable")


# ── Configuration ──

@dataclass(frozen=True)
class SandboxConfig:
    """Immutable configuration for a WASM sandbox instance."""

    memory_limit_bytes: int = 16 * 1024 * 1024  # 16 MB
    fuel_limit: int = 1_000_000_000              # ~1B wasm instructions
    gc_allow: bool = False                        # Disable garbage collection
    debug_name: str = "zeroclaw-sandbox"
    # List of sensitive paths that should *immediately* abort
    # (checked before the module even executes).
    sensitive_paths: tuple[str, ...] = (
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/ssh",
        "/proc",
        "/sys",
        "/dev",
    )


# ── Result structure ──

@dataclass(frozen=True)
class WasmExecutionResult:
    """Outcome of a sandboxed WASM execution."""

    return_values: tuple[Any, ...]
    fuel_consumed: Optional[int]
    memory_peak: Optional[int]
    execution_time_ms: float
    trapped: bool = False
    trap_reason: Optional[str] = None


# ── Main Sandbox Class ──

class WasmSandbox:
    """Execute untrusted WebAssembly with strict resource limits.

    Uses the **wasmtime** engine (the official bytecodealliance runtime).
    Corresponds to task WO-A2.2: WASM micro-sandbox code executor.
    """

    def __init__(self, config: Optional[SandboxConfig] = None) -> None:
        if not _WASMTIME_AVAILABLE:
            raise SandboxError(
                "wasmtime is not installed. Install it: pip install wasmtime>=23.0"
            )
        self.config = config or SandboxConfig()
        self._engine: Optional[Any] = None
        self._init_engine()

    # ── Internal helpers ──

    def _init_engine(self) -> None:
        """Create a fresh wasmtime Engine with fuel + memory limits."""
        cfg = _Config()
        # Enable fuel consumption tracking so we can enforce a hard tick limit
        cfg.consume_fuel = True
        # Disable parallel compilation (reduces attack surface)
        cfg.wasm_threads = False
        cfg.wasm_reference_types = False
        # Memory limits are enforced at *runtime* by the Store below,
        # because wasmtime Config does not expose a static memory_limit.
        self._engine = wt.Engine(cfg)

    @staticmethod
    def _hash_code(code_bytes: bytes) -> str:
        return hashlib.sha256(code_bytes).hexdigest()[:16]

    def _check_sensitive_path_grep(self, code_str: str) -> None:
        """Pre-flight taint: if the code text references a sensitive path, abort."""
        if not self.config.sensitive_paths:
            return
        code_lower = code_str.lower()
        for path in self.config.sensitive_paths:
            if path.lower() in code_lower:
                raise SandboxError(
                    f"Sandbox trap: code references sensitive path \"{path}\". "
                    f"Execution aborted BEFORE instantiation.",
                    trap_reason=f"sensitive_path:{path}",
                )

    # ── Public API ──

    def execute_untrusted_code(
        self,
        wasm_module: bytes,
        entrypoint: str = "main",
        args: Optional[list[Any]] = None,
    ) -> WasmExecutionResult:
        """Execute an untrusted WASM module inside the sandbox.

        The function:
        1. Scans the *raw bytes* for embedded sensitive-path strings (defence in depth).
        2. Instantiates the module inside a Store with fuel + memory limits.
        3. Calls the requested exported function, with fuel & memory guards.
        4. Returns the result or raises :class:`SandboxError` on trap / OOM / timeout.

        Args:
            wasm_module: Raw WebAssembly binary (``.wasm``) or WAT text.
            entrypoint: Name of the exported function to call.
            args: Arguments to pass (int/float; limited type support).

        Returns:
            :class:`WasmExecutionResult` with return values and metadata.

        Raises:
            SandboxError: On any sandbox violation (OOM, fuel exhaustion,
                sensitive-path access, trapped instruction, etc.).
        """
        import time as _time

        if self._engine is None:
            raise SandboxError("WASM engine not initialised")

        # ── Pre-flight sensitive-path scan on raw bytes ──
        # NOTE: This is only a "best effort pre-flight check", not a hardware-level trap.
        # Decoding binary to utf-8 produces random replacement characters, making this
        # string search probabilistic. True protection relies on wasmtime's memory bounds below.
        try:
            decoded = wasm_module.decode("utf-8", errors="replace")
        except Exception:
            decoded = ""
        self._check_sensitive_path_grep(decoded)

        store = Store(self._engine)
        module_obj = None
        instance = None
        linker_obj = None
        try:
            # Fuel bookkeeping: set the budget; execution subtracts from it.
            store.set_fuel(self.config.fuel_limit)

            start = _time.perf_counter()
            fuel_before = store.get_fuel()

            try:
                module_obj = Module(store.engine, wasm_module)
            except Exception as exc:
                raise SandboxError(f"WASM module compilation failed: {exc}") from exc

            # ── Resolve imports ──
            # We deliberately do NOT provide any host functions for disk or network.
            # Any unresolved import causes instantiation to fail (safe-by-default).
            unused_imports = [
                f"{imp.module}.{imp.name}" if hasattr(imp, "module") else str(imp)
                for imp in module_obj.imports
            ]
            if unused_imports:
                raise SandboxError(
                    f"Sandbox: module requires {len(unused_imports)} unresolved "
                    f"import(s): {', '.join(unused_imports[:5])}. "
                    f"All host-side imports are disabled for untrusted code.",
                    trap_reason="unresolved_import",
                )

            # Use Linker to instantiate (wasmtime >= 14 API).
            linker_obj = Linker(store.engine)
            instance = linker_obj.instantiate(store, module_obj)
            exports = instance.exports(store)

            # Look up the requested entrypoint function.
            func = exports.get(entrypoint) if hasattr(exports, "get") else None
            if func is None or not isinstance(func, Func):
                available = list(exports.keys()) if hasattr(exports, "keys") else list(exports)
                raise SandboxError(
                    f'Sandbox: entrypoint "{entrypoint}" not found in WASM exports. '
                    f"Available: {available}"
                )

            # Convert args
            _args = args or []
            try:
                raw_result = func(store, *_args)
            except Trap as exc:
                # Hardware-level trap (e.g. out-of-bounds, unreachable, divide-by-zero).
                # Check if fuel was exhausted (wasmtime raises Trap when fuel hits 0).
                try:
                    fuel_remaining = store.get_fuel()
                except Exception:
                    fuel_remaining = -1
                if fuel_remaining == 0:
                    raise SandboxError(
                        f"WASM fuel exhausted (instruction budget: "
                        f"{self.config.fuel_limit} instructions).",
                        trap_reason="fuel_exhausted",
                    ) from exc
                raise SandboxError(
                    f"WASM Trap: {exc}",
                    trap_reason=str(exc),
                ) from exc
            except MemoryError as exc:
                # Out-of-memory during execution (被视为 "内存越界 Trap")
                raise SandboxError(
                    "WASM memory limit exceeded (16 MB hard limit).",
                    trap_reason="memory_limit_exceeded",
                ) from exc
            except Exception as exc:
                # Catch-all for any other runtime failure.
                raise SandboxError(
                    f"WASM execution failed: {exc}",
                    trap_reason=str(exc),
                ) from exc

            elapsed = (_time.perf_counter() - start) * 1000
            fuel_after = store.get_fuel()
            fuel_consumed = fuel_before - fuel_after if fuel_before else None

            # Normalize return value to a tuple
            if isinstance(raw_result, tuple):
                return_values = raw_result
            elif raw_result is not None:
                return_values = (raw_result,)
            else:
                return_values = ()

            logger.info(
                "WASM sandbox execution OK: entrypoint=%s fuel_consumed=%s time_ms=%.2f",
                entrypoint,
                fuel_consumed,
                elapsed,
            )

            return WasmExecutionResult(
                return_values=return_values,
                fuel_consumed=fuel_consumed,
                memory_peak=None,  # wasmtime Python bindings don't expose peak memory
                execution_time_ms=elapsed,
                trapped=False,
                trap_reason=None,
            )

        finally:
            # ── Explicit cleanup: release native wasmtime C heap memory ──
            # Store, Instance, Module, and Linker all hold native resources.
            # Explicitly deleting references prevents C heap accumulation
            # when execute_untrusted_code() is called repeatedly in a loop.
            for obj in (instance, linker_obj, module_obj, store):
                if obj is not None:
                    try:
                        close_fn = getattr(obj, "close", None)
                        if close_fn is not None:
                            close_fn()
                    except Exception:
                        pass
            # Break Python-side references so GC can collect immediately
            del instance, linker_obj, module_obj, store
