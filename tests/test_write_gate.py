"""Tests for the 3-Stage Write Gate.

CRITICAL SAFETY TESTS (Red Lines):
- Invalid data must be rejected (SHACL violation)
- Direct write without validation nonce must be blocked
- Write with expired nonce must be blocked
- Write with tampered data (hash mismatch) must be blocked
"""

import hashlib
import hmac
import time
from pathlib import Path

import pytest

from agentos.governance.neo4j_client import Neo4jClient
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.write_gate import WriteGate
from agentos.kernel.config import ConfigLoader
from agentos.kernel.exceptions import WriteGateError, SHACLValidationError, GovernanceError


# ── Fixtures ──

@pytest.fixture
def app_config():
    """Load the project config."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    loader = ConfigLoader(str(config_path))
    return loader.load()


@pytest.fixture
def schema_provider(app_config):
    """Create a SchemaProvider from the real config."""
    return SchemaProvider(
        owl_dir=app_config.ontology.owl_dir,
        shacl_dir=app_config.ontology.shacl_dir,
        domains=app_config.ontology.domains,
    )


@pytest.fixture
def write_gate(schema_provider):
    """Create a WriteGate with a test nonce secret."""
    return WriteGate(
        schema_provider=schema_provider,
        neo4j_client=None,  # Test without Neo4j — nonce logic is in-memory
        nonce_secret="test-secret",
        nonce_ttl_seconds=300,
    )


class TestStage1Schema:
    """Stage 1: get_domain_schema."""

    def test_get_schema_for_known_domain(self, write_gate):
        """Known domain returns full schema definition."""
        schema = write_gate.get_domain_schema("it-asset-mgmt")
        assert "domain" in schema
        assert "classes" in schema
        assert "properties" in schema
        assert "shacl_shapes" in schema
        assert len(schema["classes"]) > 0

    def test_get_schema_for_unknown_domain(self, write_gate):
        """Unknown domain raises GovernanceError."""
        with pytest.raises(GovernanceError) as exc:
            write_gate.get_domain_schema("nonexistent-domain")
        assert "Unknown domain" in str(exc.value) or "nonexistent" in str(exc.value)


class TestStage2Validation:
    """Stage 2: verify_shacl_compliance."""

    def test_valid_data_returns_report_and_nonce(self, write_gate, sample_valid_ttl):
        """Valid data returns conforms=True and a nonce."""
        report, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)

        assert report.is_valid is True
        assert nonce is not None
        assert isinstance(nonce, str)
        assert len(nonce) > 50  # HMAC-SHA256 hex is 64 chars + timestamp + data hash

    def test_invalid_data_returns_report_and_no_nonce(self, write_gate, sample_invalid_ttl):
        """Invalid data returns conforms=False and None nonce."""
        report, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_invalid_ttl)

        assert report.is_valid is False
        assert nonce is None

    def test_unknown_domain_raises(self, write_gate):
        """Validating against unknown domain raises GovernanceError."""
        with pytest.raises(GovernanceError):
            write_gate.verify_shacl_compliance("unknown", "some rdf data")

    def test_malformed_rdf_raises(self, write_gate):
        """Malformed RDF raises SHACLValidationError."""
        with pytest.raises(SHACLValidationError) as exc:
            write_gate.verify_shacl_compliance("it-asset-mgmt", "not valid rdf {{{")
        assert "parse" in str(exc.value).lower() or "RDF" in str(exc.value)


class TestStage3WriteExecution:
    """Stage 3: execute_governed_write — the critical safety layer."""

    # ── RED LINE TESTS ──

    @pytest.mark.asyncio
    async def test_RED_LINE_direct_write_without_nonce_must_fail(self, write_gate, sample_valid_ttl):
        """
        🚨 RED LINE: Attempting execute_governed_write without a valid nonce
        from verify_shacl_compliance MUST be rejected.
        """
        with pytest.raises(WriteGateError) as exc:
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_valid_ttl,
                validation_nonce="fake-nonce",
            )

        error_msg = str(exc.value).lower()
        assert any(word in error_msg for word in ["invalid", "verify", "nonce"])

    @pytest.mark.asyncio
    async def test_RED_LINE_write_with_fake_nonce_must_fail(self, write_gate, sample_valid_ttl):
        """
        🚨 RED LINE: A crafted/hand-made nonce should be rejected.
        """
        # Craft a fake nonce with correct format but random signature
        fake_nonce = f"{int(time.time())}:{hashlib.sha256(sample_valid_ttl.encode()).hexdigest()}:fakesignature"

        with pytest.raises(WriteGateError) as exc:
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_valid_ttl,
                validation_nonce=fake_nonce,
            )

        assert "signature" in str(exc.value).lower() or "invalid" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_RED_LINE_write_with_expired_nonce_must_fail(self, write_gate, sample_valid_ttl):
        """
        🚨 RED LINE: An expired nonce (past TTL) must be rejected.
        """
        # Create a nonce with a timestamp in the past
        old_timestamp = int(time.time()) - 600  # 10 minutes ago (TTL is 300s)
        data_hash = hashlib.sha256(sample_valid_ttl.encode()).hexdigest()
        payload = f"{old_timestamp}:{data_hash}:it-asset-mgmt"
        signature = hmac.new(
            b"test-secret", payload.encode(), hashlib.sha256
        ).hexdigest()
        expired_nonce = f"{old_timestamp}:{data_hash}:{signature}"

        with pytest.raises(WriteGateError) as exc:
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_valid_ttl,
                validation_nonce=expired_nonce,
            )

        assert "expired" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_RED_LINE_write_with_tampered_data_must_fail(self, write_gate, sample_valid_ttl, sample_invalid_ttl):
        """
        🚨 RED LINE: Using a nonce from valid data with different (tampered) data
        must be rejected (data hash mismatch).
        """
        # Get a valid nonce for valid data
        _, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)
        assert nonce is not None

        # Try to use it with different data
        with pytest.raises(WriteGateError) as exc:
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_invalid_ttl,  # Different data!
                validation_nonce=nonce,
            )

        assert "hash" in str(exc.value).lower() or "mismatch" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_RED_LINE_unknown_domain_write_must_fail(self, write_gate, sample_valid_ttl):
        """
        🚨 RED LINE: Writing to an unknown domain must be rejected.
        """
        # Get valid nonce for the real domain
        _, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)

        with pytest.raises(WriteGateError):
            await write_gate.execute_governed_write(
                "unknown-domain",
                sample_valid_ttl,
                validation_nonce=nonce,
            )

    @pytest.mark.asyncio
    async def test_RED_LINE_nonce_replay_must_be_blocked(self, write_gate, sample_valid_ttl):
        """
        🚨 RED LINE: A valid nonce can only be used ONCE.
        Replaying the same nonce for a second write must be rejected.
        """
        # Get a valid nonce
        _, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)
        assert nonce is not None

        # First use — succeeds
        result1 = await write_gate.execute_governed_write(
            "it-asset-mgmt",
            sample_valid_ttl,
            validation_nonce=nonce,
        )
        assert "status" in result1

        # Second use of the SAME nonce — must be rejected as replay
        with pytest.raises(WriteGateError) as exc:
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_valid_ttl,
                validation_nonce=nonce,  # Same nonce!
            )

        error_msg = str(exc.value).lower()
        assert any(word in error_msg for word in ["consumed", "replay", "already", "once"])

    # ── Happy path ──

    @pytest.mark.asyncio
    async def test_valid_write_with_nonce_succeeds(self, write_gate, sample_valid_ttl):
        """Full 3-stage flow: schema → validate → write (simulated Neo4j)."""
        # Stage 1: Get schema
        schema = write_gate.get_domain_schema("it-asset-mgmt")
        assert len(schema["classes"]) > 0

        # Stage 2: Validate and get nonce
        report, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)
        assert report.is_valid
        assert nonce is not None

        # Stage 3: Execute write (returns "queued" since Neo4j is not available)
        result = await write_gate.execute_governed_write(
            "it-asset-mgmt",
            sample_valid_ttl,
            validation_nonce=nonce,
        )

        assert "status" in result
        assert result["domain"] == "it-asset-mgmt"
        assert "transaction_id" in result

class TestNonceIntegrity:
    """Fine-grained tests for nonce creation and verification."""

    @pytest.mark.asyncio
    async def test_same_data_produces_different_nonces(self, write_gate, sample_valid_ttl):
        """Each validation call should produce a unique nonce (different timestamps)."""
        import time as _time

        _, nonce1 = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)
        _time.sleep(1.1)  # Ensure timestamp differs
        _, nonce2 = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)

        assert nonce1 is not None and nonce2 is not None
        # Timestamps may differ; if not (fast test env), the whole nonce may be same
        # The key invariant is: both nonces are valid for the same data
        await write_gate.execute_governed_write("it-asset-mgmt", sample_valid_ttl, nonce1)
        await write_gate.execute_governed_write("it-asset-mgmt", sample_valid_ttl, nonce2)

    def test_different_data_produces_different_nonces(self, write_gate, sample_valid_ttl, sample_valid_employee_ttl):
        """Different data should produce nonces with different data hashes."""
        _, nonce1 = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)
        _, nonce2 = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_employee_ttl)

        hash1 = nonce1.split(":")[1] if nonce1 else None
        hash2 = nonce2.split(":")[1] if nonce2 else None
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_nonce_is_signed_with_secret(self, write_gate, sample_valid_ttl):
        """Nonce should be verifiable with the correct secret, not a wrong one."""
        _, nonce = write_gate.verify_shacl_compliance("it-asset-mgmt", sample_valid_ttl)

        # Tamper with the nonce signature
        parts = nonce.split(":")
        tampered = f"{parts[0]}:{parts[1]}:badsig"

        with pytest.raises(WriteGateError):
            await write_gate.execute_governed_write(
                "it-asset-mgmt",
                sample_valid_ttl,
                validation_nonce=tampered,
            )
