"""WASM test fixture utilities — compile WAT to WASM using wasmtime.

Uses wasmtime's built-in ``wat2wasm`` to compile WebAssembly text format
to binary. No external ``wat2wasm`` from wabt is needed.
"""

from __future__ import annotations

import wasmtime


def _compile(wat: str) -> bytes:
    """Compile WAT source text to WASM binary using wasmtime."""
    return wasmtime.wat2wasm(wat)


def get_simple_add_wasm() -> bytes:
    """WASM module with an exported ``add`` function: (i32, i32) -> i32."""
    return _compile("""
        (module
          (func (export "add") (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.add))
    """)


def get_infinite_loop_wasm() -> bytes:
    """WASM module with an exported ``spin`` function that loops forever."""
    return _compile("""
        (module
          (func (export "spin")
            (loop
              (br 0))))
    """)


def get_memory_hog_wasm() -> bytes:
    """WASM module that tries to grow memory by 512 pages (32 MB).

    This exceeds the 16 MB sandbox limit and should trap.
    """
    return _compile("""
        (module
          (memory 1)
          (func (export "grow")
            (memory.grow (i32.const 512))
            drop))
    """)


def get_wasi_import_wasm() -> bytes:
    """WASM module importing ``wasi_snapshot_preview1.fd_write``.

    The sandbox must reject this since all host imports are disabled.
    """
    return _compile("""
        (module
          (import "wasi_snapshot_preview1" "fd_write"
            (func (param i32 i32 i32 i32) (result i32)))
          (func (export "do_write")))
    """)


def get_sensitive_path_wasm() -> bytes:
    """WASM module containing the string "/etc/passwd" in a custom section.

    The pre-flight sensitive-path scan should detect this and abort
    before instantiation.
    """
    # Build a valid module first, then append a custom section with the path.
    base = _compile("""
        (module
          (func (export "add") (param i32 i32) (result i32)
            local.get 0
            local.get 1
            i32.add))
    """)
    # Custom section (id=0): payload is the sensitive path string.
    # Format: name_len (LEB128) + name_bytes + content
    # We use a "name" section with embedded /etc/passwd
    custom_name = b"\x09func_name\x0b/etc/passwd"
    # Section ID 0, length-prefixed
    section_id = b"\x00"
    section_len = _encode_leb128_unsigned(len(custom_name))
    return base + section_id + section_len + custom_name


def get_invalid_wasm_bytes() -> bytes:
    """Return bytes that are NOT a valid WASM module (garbage)."""
    return b"this is not a valid wasm module!!!"


def _encode_leb128_unsigned(value: int) -> bytes:
    """Encode an unsigned integer as unsigned LEB128."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        result.append(byte)
        if value == 0:
            break
    return bytes(result)
