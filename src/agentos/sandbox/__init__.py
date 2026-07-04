"""WASM Micro-Sandbox — execute untrusted code with strict resource limits."""
from __future__ import annotations
from agentos.sandbox.wasm_executor import WasmSandbox, SandboxConfig, WasmExecutionResult

__all__ = ["WasmSandbox", "SandboxConfig", "WasmExecutionResult"]
