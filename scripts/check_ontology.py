#!/usr/bin/env python3
"""Ontology-as-Code CI/CD 自动化回归脚本 (WO-A3.3).

功能：
    当 OWL 本体文件或 SHACL 规则文件被修改时，自动拉起黄金数据集（Golden Dataset）
    进行全量回归测试，确保新修改不会破坏现有业务约束校验规则。

用法：
    # 直接运行（全量测试）
    python scripts/check_ontology.py

    # 指定本体目录
    python scripts/check_ontology.py --ontology-dir docker/ontology

    # 仅测试指定 domain
    python scripts/check_ontology.py --domain it-asset-mgmt

    # CI 模式：失败时以非零退出码退出（触发 GitHub Actions 失败）
    python scripts/check_ontology.py --ci

集成到 Git Pre-commit Hook：
    # .git/hooks/pre-commit
    #!/bin/sh
    if git diff --cached --name-only | grep -q 'ontology'; then
        python scripts/check_ontology.py --ci || exit 1
    fi

集成到 GitHub Actions（参见 .github/workflows/ontology-ci.yml）：
    - name: Run Ontology Regression
      run: python scripts/check_ontology.py --ci
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# 确保 src 在 path 上
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from governance.schema_provider import SchemaProvider
from governance.shacl_validator import SHACLValidator
from rdflib import Graph
from golden_dataset import ALL_CASES, GoldenCase

# 注意：日志格式含义说明：✅ 通过 | ❌ 失败 | ⚠️ 警告
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
)
logger = logging.getLogger("check_ontology")


# ── ANSI 颜色码（若终端不支持可通过 --no-color 关闭）──
class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _c(text: str, color: str, use_color: bool = True) -> str:
    return f"{color}{text}{Color.RESET}" if use_color else text


# ── 单测案例执行 ──

def run_case(
    case: GoldenCase,
    validator: SHACLValidator,
    use_color: bool = True,
) -> tuple[bool, Optional[str]]:
    """对单个黄金案例执行 SHACL 校验，返回 (passed, error_detail)。

    passed=True  表示测试结果符合预期（无论数据是否合规）。
    passed=False 表示测试结果与预期相反（假阳性或假阴性）。
    """
    try:
        # 将 TTL 字符串解析为 rdflib Graph 再送入 validator
        data_graph = Graph()
        data_graph.parse(data=case.ttl_data, format="turtle")
        report = validator.validate(data_graph)
        is_valid = report.is_valid

        if is_valid == case.expected_valid:
            # 符合预期
            return True, None
        else:
            # 结果与预期相反
            if case.expected_valid:
                # 数据应有效，但校验失败 → 假阳性（本体过于严格）
                violations = "; ".join(
                    v.get("resultMessage", "") for v in report.results
                )
                return False, f"期望 VALID 但校验失败（假阳性）: {violations}"
            else:
                # 数据应无效，但校验通过 → 假阴性（本体规则被删除/削弱）
                return False, (
                    f"期望 INVALID 但校验通过（假阴性）— "
                    f"预期违规关键词: {case.expected_violations}"
                )
    except Exception as exc:
        return False, f"执行异常: {exc}"


# ── 主流程 ──

def main() -> int:
    """返回退出码：0=全部通过，1=有测试失败，2=环境错误。"""
    parser = argparse.ArgumentParser(
        description="Ontology-as-Code SHACL 回归测试 CI 脚本"
    )
    parser.add_argument(
        "--ontology-dir",
        default=str(_REPO_ROOT / "docker" / "ontology"),
        help="OWL/SHACL 文件目录（default: docker/ontology）",
    )
    parser.add_argument(
        "--domain",
        default="it-asset-mgmt",
        help="要测试的 ontology domain 名称（default: it-asset-mgmt）",
    )
    parser.add_argument(
        "--shacl-file",
        default=None,
        help="指定覆盖的 SHACL 文件路径（default: 从 domain 自动推断）",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI 模式：测试失败时以 exit(1) 终止",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用 ANSI 颜色输出",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="打印每个案例的详细 SHACL 报告",
    )
    args = parser.parse_args()

    use_color = not args.no_color
    ontology_dir = Path(args.ontology_dir)

    print(
        "\n"
        + _c("=" * 65, Color.BOLD, use_color)
        + "\n"
        + _c("  🔬 Ontology-as-Code SHACL 回归测试", Color.BOLD, use_color)
        + "\n"
        + _c("=" * 65, Color.BOLD, use_color)
    )
    print(f"  本体目录: {ontology_dir}")
    print(f"  Domain:   {args.domain}")
    print(f"  总案例数: {len(ALL_CASES)}")

    # ── 初始化 SHACL 校验器 ──
    shacl_file = args.shacl_file
    if shacl_file is None:
        shacl_file = str(ontology_dir / f"{args.domain}.shacl.ttl")

    shacl_path = Path(shacl_file)
    if not shacl_path.exists():
        print(
            _c(f"\n❌ SHACL 文件不存在: {shacl_path}", Color.RED, use_color)
            + "\n   请检查 --ontology-dir 和 --domain 参数"
        )
        return 2

    try:
        # SHACLValidator.from_file 会读取 TTL 并初始化 shacl_graph
        validator = SHACLValidator.from_file(str(shacl_path))
    except Exception as exc:
        print(_c(f"\n❌ 加载 SHACL 失败: {exc}", Color.RED, use_color))
        return 2

    print(f"  SHACL:    {shacl_path.name}")
    print(_c("-" * 65, Color.BOLD, use_color) + "\n")

    # ── 执行所有测试案例 ──
    passed_count = 0
    failed_count = 0
    failed_cases: list[tuple[GoldenCase, str]] = []
    start_time = time.time()

    for case in ALL_CASES:
        ok, error = run_case(case, validator, use_color)

        if ok:
            passed_count += 1
            status = _c("✅ PASS", Color.GREEN, use_color)
            validity = "VALID" if case.expected_valid else "INVALID (expected)"
            print(f"  {status}  [{validity}]  {case.name}")
            if args.verbose:
                print(f"         └─ {case.description}")
        else:
            failed_count += 1
            failed_cases.append((case, error or ""))
            status = _c("❌ FAIL", Color.RED, use_color)
            validity = "VALID" if case.expected_valid else "INVALID (expected)"
            print(f"  {status}  [{validity}]  {case.name}")
            print(f"         └─ {_c(error or '', Color.YELLOW, use_color)}")

    elapsed = time.time() - start_time

    # ── 汇总输出 ──
    print("\n" + _c("=" * 65, Color.BOLD, use_color))
    print(f"  📊 测试结果汇总 ({elapsed:.2f}s)")
    print(_c("-" * 65, Color.BOLD, use_color))
    print(f"  总案例: {len(ALL_CASES)}")
    print(f"  通过:   {_c(str(passed_count), Color.GREEN, use_color)}")
    if failed_count > 0:
        print(f"  失败:   {_c(str(failed_count), Color.RED, use_color)}")
    else:
        print(f"  失败:   {failed_count}")

    if failed_cases:
        print("\n" + _c("  ❌ 失败案例详情:", Color.RED, use_color))
        for fc, err in failed_cases:
            print(f"    • {fc.name}")
            print(f"      期望: {'VALID' if fc.expected_valid else 'INVALID'}")
            print(f"      错误: {err}")
            print(f"      描述: {fc.description}")

        print(
            "\n"
            + _c("  ⚠️  SHACL 回归测试失败！本体修改可能破坏了现有业务约束。", Color.RED, use_color)
        )
        print(_c("     请在合并 PR 前修复上述问题。", Color.RED, use_color))
        print(_c("=" * 65, Color.BOLD, use_color) + "\n")
        return 1
    else:
        print(
            "\n"
            + _c("  🎉 全部回归测试通过！本体修改未破坏任何现有约束。", Color.GREEN, use_color)
        )
        print(_c("=" * 65, Color.BOLD, use_color) + "\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
