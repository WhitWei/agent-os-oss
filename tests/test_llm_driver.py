"""Tests for LLMDriver (unit tests, no API key needed)."""

from __future__ import annotations

import pytest

from agentos_kernel.llm_driver import (
    ClaudeDriver,
    FallbackDriver,
    IntentResult,
    RDFGenerationResult,
)


class TestFallbackDriver:
    """Test the keyword-pattern fallback driver (no LLM API needed)."""

    @pytest.fixture
    def driver(self) -> FallbackDriver:
        return FallbackDriver()

    @pytest.fixture
    def domains(self) -> list[str]:
        return ["it-asset-mgmt", "sales-contract"]

    @pytest.mark.asyncio
    async def test_query_schema_intent(self, driver: FallbackDriver, domains: list[str]) -> None:
        result = await driver.decide_intent("show me the schema for it-asset-mgmt", domains)
        assert result.intent == "query_schema"
        assert result.domain == "it-asset-mgmt"

    @pytest.mark.asyncio
    async def test_validate_intent(self, driver: FallbackDriver, domains: list[str]) -> None:
        result = await driver.decide_intent("validate this employee data", domains)
        assert result.intent == "validate"

    @pytest.mark.asyncio
    async def test_governed_write_intent(self, driver: FallbackDriver, domains: list[str]) -> None:
        result = await driver.decide_intent("create a new asset assignment", domains)
        assert result.intent == "governed_write"
        assert result.domain == "it-asset-mgmt"

    @pytest.mark.asyncio
    async def test_governed_write_with_sales_domain(self, driver: FallbackDriver, domains: list[str]) -> None:
        result = await driver.decide_intent("I need to write a sales contract", domains)
        assert result.intent == "governed_write"
        assert result.domain == "sales-contract"

    @pytest.mark.asyncio
    async def test_unknown_intent(self, driver: FallbackDriver, domains: list[str]) -> None:
        result = await driver.decide_intent("hello, how are you?", domains)
        assert result.intent == "unknown"

    @pytest.mark.asyncio
    async def test_empty_domains(self, driver: FallbackDriver) -> None:
        result = await driver.decide_intent("validate", [])
        assert result.intent == "validate"
        assert result.domain == ""

    @pytest.mark.asyncio
    async def test_generate_rdf_returns_error(self, driver: FallbackDriver) -> None:
        result = await driver.generate_rdf("it-asset-mgmt", {}, "some data")
        assert result.valid is False
        assert "ANTHROPIC_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_route_to_sop_returns_empty(self, driver: FallbackDriver) -> None:
        sop_id = await driver.route_to_sop("onboard employee", [{"sop_id": "abc"}])
        assert sop_id == ""


class TestClaudeDriverNoApiKey:
    """Test ClaudeDriver without API key — should behave like FallbackDriver."""

    @pytest.fixture
    def driver(self) -> ClaudeDriver:
        return ClaudeDriver(api_key="")  # No real key

    @pytest.mark.asyncio
    async def test_fallback_without_key(self, driver: ClaudeDriver) -> None:
        result = await driver.decide_intent("show schema", ["it-asset-mgmt"])
        # Without SDK or key, should fall back gracefully
        assert result.intent in ("query_schema", "unknown")

    @pytest.mark.asyncio
    async def test_rdf_fails_without_key(self, driver: ClaudeDriver) -> None:
        result = await driver.generate_rdf("it-asset-mgmt", {}, "test")
        assert result.valid is False


class TestIntentResult:
    """Test IntentResult data class."""

    def test_default_values(self) -> None:
        r = IntentResult()
        assert r.intent == "unknown"
        assert r.confidence == 0.0
        assert r.domain == ""

    def test_custom_values(self) -> None:
        r = IntentResult(
            intent="start_sop",
            domain="it-asset-mgmt",
            sop_id="onboarding-v1",
            raw_text="onboard new employee",
            confidence=0.95,
        )
        assert r.intent == "start_sop"
        assert r.sop_id == "onboarding-v1"
        assert r.confidence == 0.95


class TestRDFGenerationResult:
    """Test RDFGenerationResult data class."""

    def test_default_values(self) -> None:
        r = RDFGenerationResult()
        assert r.valid is False
        assert r.rdf_turtle == ""

    def test_success(self) -> None:
        turtle = "@prefix ex: <http://example.org/> . ex:A a ex:B ."
        r = RDFGenerationResult(rdf_turtle=turtle, domain="it-asset-mgmt", valid=True)
        assert r.valid
        assert "ex:A" in r.rdf_turtle
