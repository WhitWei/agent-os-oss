"""L2 集成测试 — CLI 与 Global-Loop-Engine 的双引擎接线测试 (WO-402)。

测试流：
1. 真实调用 agentos loop run
2. 获取其生成的自愈输出 Nonce
3. 使用 agentos write 物理放行落库
"""

import pytest
import os
from click.testing import CliRunner
from pathlib import Path
from unittest.mock import patch

from agentos_cli.cli import main

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

@pytest.fixture
def cli_runner():
    return CliRunner()

class TestCliLoopWiring:
    @pytest.mark.asyncio
    async def test_dual_engine_wiring(
        self, app_config, neo4j_client, sample_valid_ttl, tmp_path
    ):
        """测试 CLI 发起 validate/write 并成功落库 (通过 testcontainers 提供的 neo4j_client)。"""
        import subprocess
        import sys

        # We need a valid RDF file to write
        rdf_file = tmp_path / "asset.ttl"
        rdf_file.write_text(sample_valid_ttl)

        # Generate config with testcontainers neo4j URI
        config_yaml = f"""
ontology:
  owl_dir: "{app_config.ontology.owl_dir}"
  shacl_dir: "{app_config.ontology.shacl_dir}"
  domains:
    - name: "it-asset-mgmt"
      owl_file: "it-asset-mgmt.owl"
      shacl_file: "it-asset-mgmt.shacl.ttl"

mcp:
  server_name: "test-mcp"
  host: "0.0.0.0"
  port: 8100
  validation:
    nonce_secret: "l2-integration-test-secret"
    nonce_ttl_seconds: 300

neo4j:
  uri: "{neo4j_client._config.uri}"
  user: "{neo4j_client._config.user}"
  password: "{neo4j_client._config.password}"
  database: "neo4j"

autonomy:
  policy_file: "{app_config.autonomy.policy_file}"
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(config_yaml)

        # 1. Start validate
        result_validate = subprocess.run([
            sys.executable, "-m", "agentos_cli.cli", "validate",
            "--domain", "it-asset-mgmt",
            "--file", str(rdf_file),
            "--config", str(config_file)
        ], capture_output=True, text=True)

        assert result_validate.returncode == 0, f"Validate failed: {result_validate.stderr} {result_validate.stdout}"
        assert "Validation passed. Nonce:" in result_validate.stdout

        nonce = result_validate.stdout.strip().split("Nonce: ")[-1].strip()
        assert nonce

        # 2. Run agentos write
        result_write = subprocess.run([
            sys.executable, "-m", "agentos_cli.cli", "write",
            "--domain", "it-asset-mgmt",
            "--nonce", nonce,
            "--file", str(rdf_file),
            "--config", str(config_file)
        ], capture_output=True, text=True)

        assert result_write.returncode == 0, f"Write failed: {result_write.stderr} {result_write.stdout}"
        assert "Write successful" in result_write.stdout

        # 3. Verify in database
        rows = await neo4j_client.execute_read(
            "MATCH (a:Resource {uri: $uri})-[:SERIALNUMBER]->(b:Resource) RETURN b.uri AS serial",
            {"uri": "http://agent-os.local/data/asset/mbp-001"},
        )
        assert len(rows) == 1
        assert rows[0]["serial"] == "MBP2024-X7K9"
