"""SHACL 回归测试黄金数据集 (Golden Dataset).

用于 CI/CD 流水线（scripts/check_ontology.py）和本地回归测试。
每个测试案例声明：
  - 名称（name）
  - RDF 数据（Turtle 格式字符串）
  - 期望结果（expected_valid: True | False）
  - 预期违规消息关键词（expected_violations）— 仅 expected_valid=False 时有意义
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoldenCase:
    """单个黄金测试案例。"""
    name: str
    ttl_data: str
    expected_valid: bool
    expected_violations: list[str] = field(default_factory=list)
    description: str = ""


# ── 有效数据案例 ──────────────────────────────────────────────────

VALID_EMPLOYEE = GoldenCase(
    name="valid_employee_basic",
    description="合法的员工数据，包含 employeeId 和 employeeName",
    expected_valid=True,
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-golden-001>
    rdf:type asset:Employee ;
    asset:employeeId "EMP-GOLDEN-001" ;
    asset:employeeName "张三" .
""",
)

VALID_HARDWARE_ASSET_MEDIUM = GoldenCase(
    name="valid_hardware_asset_medium_sensitivity",
    description="合法的硬件资产，MEDIUM 敏感等级",
    expected_valid=True,
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/mbp-golden-001>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "MBP2024-GOLDEN-X7K9" ;
    asset:assetModel "MacBook Pro 16-inch M4" ;
    asset:sensitivityLevel "MEDIUM" .
""",
)

VALID_HARDWARE_ASSET_LOW = GoldenCase(
    name="valid_hardware_asset_low_sensitivity",
    description="合法的硬件资产，LOW 敏感等级，无 sensitivityLevel 字段（可选）",
    expected_valid=True,
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/keyboard-001>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "KB2024-001" ;
    asset:assetModel "Magic Keyboard" .
""",
)

VALID_SOFTWARE_ASSET = GoldenCase(
    name="valid_software_asset",
    description="合法的软件资产，包含 licenseKey 和 softwareName",
    expected_valid=True,
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/sw-figma-001>
    rdf:type asset:SoftwareAsset ;
    asset:licenseKey "FIGMA-ENT-2024-GOLDEN" ;
    asset:softwareName "Figma Enterprise" .
""",
)

# ── 无效数据案例 ──────────────────────────────────────────────────

INVALID_HARDWARE_MISSING_SERIAL = GoldenCase(
    name="invalid_hardware_missing_serial_number",
    description="缺少 serialNumber（必填字段），应触发 SHACL 违规",
    expected_valid=False,
    expected_violations=["serialNumber", "minCount"],
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/laptop-no-serial>
    rdf:type asset:HardwareAsset ;
    asset:assetModel "ThinkPad X1 Carbon" .
""",
)

INVALID_HARDWARE_MISSING_MODEL = GoldenCase(
    name="invalid_hardware_missing_model",
    description="缺少 assetModel（必填字段），应触发 SHACL 违规",
    expected_valid=False,
    expected_violations=["assetModel", "minCount"],
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/laptop-no-model>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "SN-NO-MODEL-001" .
""",
)

INVALID_EMPLOYEE_MISSING_ID = GoldenCase(
    name="invalid_employee_missing_id",
    description="缺少 employeeId（必填字段），应触发 SHACL 违规",
    expected_valid=False,
    expected_violations=["employeeId", "minCount"],
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-no-id>
    rdf:type asset:Employee ;
    asset:employeeName "李四" .
""",
)

INVALID_EMPLOYEE_MISSING_NAME = GoldenCase(
    name="invalid_employee_missing_name",
    description="缺少 employeeName（必填字段），应触发 SHACL 违规",
    expected_valid=False,
    expected_violations=["employeeName", "minCount"],
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-no-name>
    rdf:type asset:Employee ;
    asset:employeeId "EMP-NO-NAME" .
""",
)

INVALID_SOFTWARE_MISSING_LICENSE = GoldenCase(
    name="invalid_software_missing_license",
    description="缺少 licenseKey（必填字段），应触发 SHACL 违规",
    expected_valid=False,
    expected_violations=["licenseKey", "minCount"],
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/sw-no-license>
    rdf:type asset:SoftwareAsset ;
    asset:softwareName "Adobe Photoshop" .
""",
)

# UAT 场景专用：高管敏感设备（WO-A3.4 触发审批条件）
VALID_CRITICAL_ASSET_FOR_UAT = GoldenCase(
    name="valid_critical_hardware_asset_uat",
    description="CRITICAL 敏感等级设备 — 数据本身 SHACL 合规，但业务逻辑上需要人工审批",
    expected_valid=True,
    ttl_data="""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/mbp-exec-001>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "MBP2024-EXEC-001" ;
    asset:assetModel "MacBook Pro 16-inch M4 Max (64GB)" ;
    asset:sensitivityLevel "CRITICAL" .
""",
)


# ── 全量数据集（按顺序排列，用于 CI 脚本遍历）──────────────────────

ALL_CASES: list[GoldenCase] = [
    VALID_EMPLOYEE,
    VALID_HARDWARE_ASSET_MEDIUM,
    VALID_HARDWARE_ASSET_LOW,
    VALID_SOFTWARE_ASSET,
    VALID_CRITICAL_ASSET_FOR_UAT,
    INVALID_HARDWARE_MISSING_SERIAL,
    INVALID_HARDWARE_MISSING_MODEL,
    INVALID_EMPLOYEE_MISSING_ID,
    INVALID_EMPLOYEE_MISSING_NAME,
    INVALID_SOFTWARE_MISSING_LICENSE,
]

VALID_CASES = [c for c in ALL_CASES if c.expected_valid]
INVALID_CASES = [c for c in ALL_CASES if not c.expected_valid]
