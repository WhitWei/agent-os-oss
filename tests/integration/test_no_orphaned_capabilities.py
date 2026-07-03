"""L2 集成测试 — 孤儿能力接线检测的 CI 门禁包装 (Rule 10.4)。

把 scripts/check_wiring.py 的静态扫描接入 pytest,使其成为常驻回归项:
任何新增的安全/治理能力,只要没有被生产入口代码真实调用,CI 就必须变红,
而不是依赖人工 review 才发现"组件造好了但没接线"。

本测试刻意不去"让它变绿" —— 如果扫描结果里有未登记的孤儿能力,这条测试
必须失败,如实反映当前接线状态。是否要接线、删除,还是写明理由加入
scripts/check_wiring.py 的 ALLOWLIST,是需要人来决定的架构问题,不是
测试基础设施应该替人决定的事。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_check_wiring_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_wiring.py"
    spec = importlib.util.spec_from_file_location("check_wiring", script_path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses 内部会用 sys.modules.get(cls.__module__) 反查模块解析类型注解，
    # 动态加载的模块必须先注册进 sys.modules，否则 @dataclass 装饰器会炸。
    sys.modules["check_wiring"] = module
    spec.loader.exec_module(module)
    return module


def test_no_unregistered_orphaned_capabilities():
    check_wiring = _load_check_wiring_module()
    orphans, allowlisted = check_wiring.run_check(verbose=False)

    if orphans:
        details = "\n".join(
            f"  - {cap.name} (定义于 {cap.defined_in})，在 src/ 下没有任何生产调用点"
            for cap in orphans
        )
        raise AssertionError(
            "发现未登记的孤儿能力 —— 该组件的单元测试可能全部通过,但主运行路径"
            "(kernel.py / mcp_server.py / write_gate.py 等)从未真正调用它。\n"
            f"{details}\n"
            "处理方式三选一:\n"
            "  1) 把它接入真实的生产入口代码路径；\n"
            "  2) 如果确实不再需要，直接删除该能力；\n"
            "  3) 如果是有意预留的未来能力，在 scripts/check_wiring.py 的 "
            "ALLOWLIST 中登记并写明理由（不允许静默豁免）。"
        )
