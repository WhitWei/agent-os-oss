#!/usr/bin/env python3
"""孤儿能力(接线)静态检测器 —— Rule 10.4。

扫描 src/ 下声明的"能力"(安全/治理相关的类与方法),检查它们是否在生产入口
代码路径(kernel.py、mcp_server.py、write_gate.py 等)中被真实调用。

判定原则:
    只在自己的定义文件、__init__.py(仅 re-export)、scripts/ 演示脚本、
    tests/ 单测里出现的能力,一律判定为"孤儿能力" —— 它可能被单测证明
    "自身逻辑没坏",但主运行路径从未真正用到它。这正是本仓库出现过的
    "组件全部单测通过,但在 kernel.wake_up() 里从未被调用" 这一类缺陷的
    静态早期预警版本。

用法:
    python3 scripts/check_wiring.py [--verbose]

退出码:
    0 —— 没有未登记的孤儿能力
    1 —— 发现未登记的孤儿能力(需要接线 / 删除 / 写明原因加入 ALLOWLIST)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

EXCLUDED_DIR_PARTS = {"__pycache__"}


@dataclass(frozen=True)
class Capability:
    name: str          # 展示名(类名，或 "Class.method_name")
    call_pattern: str  # 调用形态的正则(不是定义形态)
    defined_in: str    # 定义该能力的文件(相对仓库根目录)，本身不算"接线证据"


# 目前纳入检测的能力清单。新增一个安全/治理组件时，应同步在这里补一条 —— 这也是
# Rule 10.4 落地的方式：新组件从第一天起就被纳入接线检测，而不是靠事后审计发现。
CAPABILITIES = [
    Capability("SemanticFirewall", r"\bSemanticFirewall\s*\(", "src/security/firewall.py"),
    Capability("CircuitBreaker", r"\bCircuitBreaker\s*\(", "src/security/circuit_breaker.py"),
    Capability("BillingFuse", r"\bBillingFuse\s*\(", "src/security/billing_fuse.py"),
    Capability("WasmSandbox", r"\bWasmSandbox\s*\(", "src/sandbox/wasm_executor.py"),
    Capability(
        "AutonomyPolicy.check_path_access",
        r"\.check_path_access\s*\(",
        "src/policies/autonomy_policy.py",
    ),
    Capability(
        "AutonomyPolicy.check_write_quota",
        r"\.check_write_quota\s*\(",
        "src/policies/autonomy_policy.py",
    ),
    Capability(
        "AutonomyPolicy.check_command",
        r"\.check_command\s*\(",
        "src/policies/autonomy_policy.py",
    ),
    Capability(
        "AutonomyPolicy.check_session_alive",
        r"\.check_session_alive\s*\(",
        "src/policies/autonomy_policy.py",
    ),
]

# 已知孤儿的豁免登记表。每一条都必须写明理由 —— 不允许静默豁免。
# 豁免不等于"没问题"，只是把"要不要接线"这个决定显式移交给人工评审。
ALLOWLIST: dict[str, str] = {
    "WasmSandbox": "WasmSandbox 目前作为 L1.5 预置底层计算沙箱，在未来引入执行外部第三方不受信插件/工具代码的逻辑时会被正式装配调用。",
    "AutonomyPolicy.check_path_access": "文件系统白名单检测 check_path_access 目前作为声明式安全保护能力，后续将在接入文件读写等工具执行器时进行物理挂载。",
}


def _is_production_file(path: Path) -> bool:
    """判定一个文件是否算"生产入口代码"（会计入接线证据）。

    排除：__pycache__、__init__.py（只是 re-export，不构成真实调用）。
    刻意只扫描 src/ 目录 —— scripts/ 演示脚本和 tests/ 单测天然被排除在外，
    因为调用方不传入 src/ 之外的路径。
    """
    rel = path.relative_to(REPO_ROOT)
    if any(part in EXCLUDED_DIR_PARTS for part in rel.parts):
        return False
    if rel.name == "__init__.py":
        return False
    return True


def find_wiring(capability: Capability) -> list[str]:
    """返回真实调用了该能力的生产文件相对路径列表（不含其自身定义文件）。"""
    pattern = re.compile(capability.call_pattern)
    defined_in = (REPO_ROOT / capability.defined_in).resolve()
    hits: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        if not _is_production_file(path):
            continue
        if path.resolve() == defined_in:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            hits.append(str(path.relative_to(REPO_ROOT)))

    return hits


def run_check(verbose: bool = True) -> tuple[list[Capability], list[tuple[Capability, str]]]:
    """执行检测，返回 (未登记孤儿列表, 已登记豁免列表)。"""
    orphans: list[Capability] = []
    allowlisted: list[tuple[Capability, str]] = []

    if verbose:
        print("=" * 78)
        print("  孤儿能力接线检测 (Rule 10.4)")
        print("=" * 78)

    for cap in CAPABILITIES:
        wired_in = find_wiring(cap)
        if wired_in:
            if verbose:
                print(f"✅ {cap.name:40s} 接线于: {', '.join(wired_in)}")
        elif cap.name in ALLOWLIST:
            allowlisted.append((cap, ALLOWLIST[cap.name]))
            if verbose:
                print(f"⚠️  {cap.name:40s} 无生产调用点，已登记豁免: {ALLOWLIST[cap.name]}")
        else:
            orphans.append(cap)
            if verbose:
                print(f"❌ {cap.name:40s} 无任何生产调用点 —— 孤儿能力")

    return orphans, allowlisted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="只输出最终结论")
    args = parser.parse_args()

    orphans, allowlisted = run_check(verbose=not args.quiet)

    print("=" * 78)
    if orphans:
        print(f"❌ 发现 {len(orphans)} 个未登记的孤儿能力，需要接线、删除，或写明原因加入 ALLOWLIST：")
        for cap in orphans:
            print(f"   - {cap.name} (定义于 {cap.defined_in})")
        return 1

    print(f"✅ 通过：0 个未登记孤儿能力（{len(allowlisted)} 个已登记豁免）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
