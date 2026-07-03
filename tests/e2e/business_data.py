"""业务场景 RDF 数据构造器 —— 每个 ID 需保持全局唯一,避免多个场景共享同一个
testcontainers Neo4j 容器时互相"串数据"。"""

from __future__ import annotations

from governance.neo4j_client import Neo4jClient


async def count_resource_nodes(neo4j_client: Neo4jClient, uri: str) -> int:
    """独立读回辅助函数 —— 所有场景断言"是否落库"时都必须走这条路径,
    不信任 SOPEngine/WriteGate 自己返回的状态字段。"""
    rows = await neo4j_client.execute_read(
        "MATCH (a:Resource {uri: $uri}) RETURN a", {"uri": uri}
    )
    return len(rows)


def employee_ttl(employee_id: str, employee_name: str) -> str:
    return f"""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/{employee_id}>
    rdf:type asset:Employee ;
    asset:employeeId "{employee_id}" ;
    asset:employeeName "{employee_name}" .
"""


def employee_ttl_missing_name(employee_id: str) -> str:
    """不合规:缺少 SHACL 要求的 asset:employeeName。"""
    return f"""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/{employee_id}>
    rdf:type asset:Employee ;
    asset:employeeId "{employee_id}" .
"""


def hardware_asset_ttl(
    asset_id: str, serial_number: str, model: str, sensitivity: str
) -> str:
    return f"""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/{asset_id}>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "{serial_number}" ;
    asset:assetModel "{model}" ;
    asset:sensitivityLevel "{sensitivity}" .
"""


def assignment_ttl(assignment_id: str, assigned_date: str = "2026-07-02") -> str:
    return f"""
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/assignment/{assignment_id}>
    rdf:type asset:AssetAssignment ;
    asset:assignedDate "{assigned_date}" .
"""


def onboarding_data(
    *,
    employee_id: str,
    employee_name: str,
    asset_id: str,
    serial_number: str,
    model: str,
    sensitivity: str,
    assignment_id: str,
    nonce: str | None = None,
) -> dict:
    """组装 it-onboarding-v1 SOP 所需的完整 ctx.data 字典。"""
    data = {
        "employee_ttl": employee_ttl(employee_id, employee_name),
        "asset_ttl": hardware_asset_ttl(asset_id, serial_number, model, sensitivity),
        "assignment_ttl": assignment_ttl(assignment_id),
        "employee_name": employee_name,
        "employee_id": employee_id,
        "asset_model": model,
        "asset_id": asset_id,
        "sensitivity_level": sensitivity,
    }
    if nonce is not None:
        data["_nonce_assignment_ttl"] = nonce
    return data
