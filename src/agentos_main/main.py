"""Agent OS Unified Service — global composition root.

Brings together the three components (AgentOSKernel, SOPEngine, FeishuAdapter)
into a single deployable FastAPI application with Feishu webhook routing.

Usage:
    uvicorn agentos_main.main:app --host 0.0.0.0 --port 8000

Architecture:
    ┌─ FastAPI (this module) ──────────────────────────┐
    │  POST /webhook/feishu  ← Feishu event subscription│
    │    ├─ verify_challenge  → {challenge: "..."}     │
    │    └─ card callback     → SOPEngine.resume()     │
    │    └─ IM message        → kernel.wake_up()       │
    │  GET  /health           → {"status": "ok"}       │
    │  GET  /api/domains      → list ontology domains  │
    │  GET  /api/sops         → list SOP YAML files    │
    │  POST /api/sops/{id}/resume → manual resume       │
    └──────────────────────────────────────────────────┘

Per architecture decision: Agent OS does NOT bundle an LLM driver.
Users Bring Their Own LLM and call the MCP governance gateway
(get_schema / verify_shacl / execute_governed_write) as tools.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Bootstrap: assemble all components from config.yaml
# ═══════════════════════════════════════════════════════════════


class ServiceBootstrap:
    """Single composition root for all Agent OS service components.

    Each component is optional — unavailable resources degrade gracefully
    rather than crash.  This is the global composition root that replaces
    the three previously independent composition roots.
    """

    def __init__(self) -> None:
        self.config = None
        self.kernel = None
        self.sop_engine = None
        self.write_gate = None
        self.schema_provider = None
        self.neo4j_client = None
        self.feedback_db = None
        self.state_store = None
        self.policy = None
        self.feishu = None
        self.available_sops: list[dict[str, Any]] = []

    async def init(self, config_path: str = "config.yaml") -> None:
        """Bootstrap all components from config file."""
        from agentos_kernel.config import ConfigLoader
        from governance.schema_provider import SchemaProvider
        from governance.write_gate import WriteGate
        from database.feedback_db import FeedbackDB
        from database.state_store import WorkflowStateStore
        from workflow.sop_engine import SOPEngine
        from policies.autonomy_policy import load_policy
        from agentos_kernel.kernel import AgentOSKernel

        # 1. Config
        logger.info("Loading config from %s ...", config_path)
        self.config = ConfigLoader(config_path).load()
        app_config = self.config

        # 2. Schema provider (ontology)
        self.schema_provider = SchemaProvider(
            owl_dir=app_config.ontology.owl_dir,
            shacl_dir=app_config.ontology.shacl_dir,
            domains=app_config.ontology.domains,
        )
        logger.info(
            "Schema provider loaded: %d domain(s)",
            len(self.schema_provider.list_domains()),
        )

        # 3. Neo4j client (optional — graceful degradation)
        try:
            from governance.neo4j_client import Neo4jClient
            self.neo4j_client = Neo4jClient(app_config.neo4j)
            healthy = await self.neo4j_client.health_check()
            if healthy:
                logger.info("Neo4j connection OK")
            else:
                logger.warning("Neo4j health check FAILED — writes will be simulated")
        except Exception as exc:
            logger.warning("Neo4j unavailable: %s — writes will be simulated", exc)
            self.neo4j_client = None

        # 4. Write gate (governance core)
        self.write_gate = WriteGate(
            schema_provider=self.schema_provider,
            neo4j_client=self.neo4j_client,
            nonce_secret=app_config.mcp.validation.nonce_secret,
            nonce_ttl_seconds=app_config.mcp.validation.nonce_ttl_seconds,
        )
        logger.info("Write gate initialised (nonce TTL=%ds)", app_config.mcp.validation.nonce_ttl_seconds)

        # 5. SQLite stores
        db_dir = Path(os.environ.get("AGENT_OS_DB_DIR", "."))
        db_dir.mkdir(parents=True, exist_ok=True)
        self.feedback_db = FeedbackDB(str(db_dir / "agentos_feedback.db"))
        self.state_store = WorkflowStateStore(str(db_dir / "agentos_state.db"))
        logger.info("SQLite stores initialised in %s", db_dir.resolve())

        # 6. Autonomy policy
        try:
            policy_path = app_config.autonomy.policy_file
            self.policy = load_policy(policy_path)
        except Exception as exc:
            logger.warning("Autonomy policy not loaded: %s — running without policy", exc)
            self.policy = None

        # 7. SOP engine (orchestration)
        self.sop_engine = SOPEngine(
            schema_provider=self.schema_provider,
            write_gate=self.write_gate,
            feedback_db=self.feedback_db,
            state_store=self.state_store,
            default_chat_id=os.environ.get("AGENT_OS_DEFAULT_CHAT_ID", ""),
        )
        logger.info("SOP engine initialised")

        # 8. Discover available SOP YAML files
        self._discover_sops()

        # 9. Agent OS kernel
        self.kernel = AgentOSKernel(
            config=app_config,
            write_gate=self.write_gate,
            autonomy_policy=self.policy,
        )
        logger.info("Agent OS kernel initialised")

        # 10. Feishu adapter (optional)
        try:
            from adapters.feishu_adapter import FeishuAdapter
            self.feishu = FeishuAdapter(
                config=app_config.adapters.feishu,
                message_handler=self._feishu_message_handler,
            )
            logger.info("Feishu adapter ready (webhook: %s)", app_config.adapters.feishu.webhook_path)
        except Exception as exc:
            logger.warning("Feishu adapter unavailable: %s", exc)
            self.feishu = None

        logger.info("✅ Agent OS unified service bootstrap complete")

    def _discover_sops(self) -> None:
        """Scan the SOP examples directory for available YAML definitions."""
        from workflow.sop_engine import SOPEngine

        sop_dirs = [
            Path("src/workflow/sop_examples"),
            Path(os.environ.get("AGENT_OS_SOP_DIR", "")),
        ]
        seen: set[str] = set()
        for d in sop_dirs:
            if not d.exists():
                continue
            for f in sorted(d.glob("*.sop.yaml")):
                try:
                    sop = SOPEngine.load_sop(str(f))
                    if sop.sop_id not in seen:
                        seen.add(sop.sop_id)
                        self.available_sops.append({
                            "sop_id": sop.sop_id,
                            "name": sop.name,
                            "description": sop.description,
                            "version": sop.version,
                            "steps": len(sop.steps),
                            "file": str(f),
                        })
                except Exception as exc:
                    logger.warning("Failed to load SOP %s: %s", f, exc)
        logger.info("Discovered %d SOP(s)", len(self.available_sops))

    async def _feishu_message_handler(self, message: Any) -> Any:
        """Handle Feishu messages by passing directly to the kernel.

        Agent OS does NOT bundle an LLM driver — users Bring Your Own LLM
        and call the MCP governance gateway tools externally.
        The kernel uses keyword-based intent detection (MVP stub).
        """
        from agentos_kernel.kernel import ChannelResponse

        if self.kernel is None:
            return ChannelResponse(
                text="Service not fully initialised yet.",
                channel=message.channel,
                metadata={"status": "error"},
                error="kernel not ready",
            )

        return await self.kernel.wake_up(message)

    async def shutdown(self) -> None:
        """Gracefully shut down all components."""
        logger.info("Shutting down Agent OS unified service...")

        if self.neo4j_client is not None:
            try:
                await self.neo4j_client.close()
            except Exception as exc:
                logger.warning("Neo4j close error: %s", exc)

        if self.feedback_db is not None:
            try:
                self.feedback_db.close()
            except Exception:
                pass

        logger.info("Shutdown complete")


# ═══════════════════════════════════════════════════════════════
# FastAPI Application Factory
# ═══════════════════════════════════════════════════════════════


def create_app(bootstrap: ServiceBootstrap | None = None) -> FastAPI:
    """Create a configured FastAPI application.

    Args:
        bootstrap: Pre-configured ServiceBootstrap.
                   Pass None for production (auto-init from config.yaml).
                   Pass a mock in tests to avoid real connections.

    Returns:
        Configured FastAPI instance.
    """
    _bootstrap_ref = bootstrap or ServiceBootstrap()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        if bootstrap is None:
            config_path = os.environ.get("AGENT_OS_CONFIG", "config.yaml")
            await _bootstrap_ref.init(config_path)
        app.state.bootstrap = _bootstrap_ref
        yield
        await _bootstrap_ref.shutdown()

    app = FastAPI(
        title="Agent OS Unified Service",
        version="0.1.0",
        description="Agent governance runtime — Feishu webhook, SOP orchestration, security guardrails",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ──

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Health check endpoint."""
        b = _bootstrap_ref
        status = "ok"
        details = {
            "kernel": b.kernel is not None,
            "sop_engine": b.sop_engine is not None,
            "write_gate": b.write_gate is not None,
            "neo4j": b.neo4j_client is not None,
            "feishu": b.feishu is not None,
            "domains": b.schema_provider.list_domains() if b.schema_provider else [],
            "sops": len(b.available_sops),
        }
        if b.kernel is None:
            status = "degraded"
        return {"status": status, "service": "agent-os", "version": "0.1.0", **details}

    # ── Feishu Webhook ──

    @app.post("/webhook/feishu")
    async def feishu_webhook(request: Request) -> dict[str, Any]:
        """Feishu event subscription webhook.

        Handles:
        1. URL verification challenge (respond with challenge token)
        2. Interactive card callback → SOPEngine.resume
        3. IM message → kernel.wake_up
        """
        b = _bootstrap_ref
        if b.feishu is None:
            raise HTTPException(status_code=503, detail="Feishu adapter not configured")

        body = await request.json()

        # 1) URL verification challenge
        challenge = b.feishu.verify_challenge(body)
        if challenge:
            return challenge

        # 2) Interactive card callback → SOPEngine.resume()
        if "action" in body:
            return await _handle_card_callback(body, b)

        # 3) IM message → parse and route to kernel
        message = b.feishu.parse_event(body)
        if message is None:
            return {"status": "ignored", "reason": "unsupported event type"}

        response = await b.kernel.wake_up(message)
        await b.feishu.send_response(response)
        return {"status": "ok", "session": response.metadata.get("session_id")}

    # ── Domain & SOP introspection ──

    @app.get("/api/domains")
    async def list_domains() -> dict[str, Any]:
        """List available ontology domains."""
        b = _bootstrap_ref
        if b.schema_provider is None:
            return {"domains": []}
        return {"domains": b.schema_provider.list_domains()}

    @app.get("/api/sops")
    async def list_sops() -> dict[str, Any]:
        """List available SOP definitions."""
        b = _bootstrap_ref
        return {"sops": b.available_sops}

    @app.get("/api/sops/{sop_id}")
    async def get_sop(sop_id: str) -> dict[str, Any]:
        """Get details for a specific SOP."""
        b = _bootstrap_ref
        for s in b.available_sops:
            if s["sop_id"] == sop_id:
                return s
        raise HTTPException(status_code=404, detail=f"SOP '{sop_id}' not found")

    @app.post("/api/sops/{run_id}/resume")
    async def resume_sop(run_id: str, request: Request) -> dict[str, Any]:
        """Manually resume a suspended SOP run.

        Request body: {"decision": "APPROVED"|"REJECTED", "reason": "...", "approver_id": "..."}
        """
        b = _bootstrap_ref
        if b.sop_engine is None or b.state_store is None:
            raise HTTPException(status_code=503, detail="SOP engine not available")

        body = await request.json()
        decision = body.get("decision", "")
        if decision not in ("APPROVED", "REJECTED"):
            raise HTTPException(status_code=400, detail="decision must be APPROVED or REJECTED")

        ctx = b.state_store.load_state(run_id)
        if ctx is None:
            raise HTTPException(status_code=404, detail=f"SOP run {run_id} not found")

        sop_def = None
        for s in b.available_sops:
            if s["sop_id"] == ctx.sop_id:
                from workflow.sop_engine import SOPEngine
                sop_def = SOPEngine.load_sop(s["file"])
                break

        if sop_def is None:
            raise HTTPException(status_code=404, detail=f"SOP definition {ctx.sop_id} not found")

        ctx = await b.sop_engine.resume(
            sop_def,
            ctx,
            decision=decision,
            reason=body.get("reason"),
            approver_id=body.get("approver_id", "api-user"),
        )

        return {
            "status": "ok",
            "run_id": run_id,
            "sop_state": ctx.state.value,
            "decision": decision,
        }

    return app


async def _handle_card_callback(body: dict[str, Any], b: ServiceBootstrap) -> dict[str, Any]:
    """Resolve an interactive card callback to SOPEngine.resume()."""
    callback = b.feishu.parse_card_callback(body)
    if callback is None:
        return {"status": "ignored", "reason": "not an approval callback"}

    if b.sop_engine is None or b.state_store is None:
        return {"status": "error", "reason": "SOP engine not available"}

    run_id = callback["run_id"]
    ctx = b.state_store.load_state(run_id)
    if ctx is None:
        return {
            "status": "error",
            "reason": f"SOP run {run_id} not found (may have expired)",
        }

    sop_def = None
    for s in b.available_sops:
        if s["sop_id"] == ctx.sop_id:
            from workflow.sop_engine import SOPEngine
            sop_def = SOPEngine.load_sop(s["file"])
            break

    if sop_def is None:
        return {"status": "error", "reason": f"SOP definition {ctx.sop_id} not found"}

    await b.sop_engine.resume(
        sop_def,
        ctx,
        decision=callback["decision"],
        reason=callback.get("reason"),
        approver_id=callback["reviewer"],
    )
    logger.info(
        "Card callback processed: run=%s decision=%s reviewer=%s",
        run_id, callback["decision"], callback["reviewer"],
    )
    return {"status": "ok", "run_id": run_id, "decision": callback["decision"]}


# ═══════════════════════════════════════════════════════════════
# Module-level instance (production use)
# ═══════════════════════════════════════════════════════════════

app = create_app()


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """Run the unified service with uvicorn."""
    import uvicorn

    app_config_path = os.environ.get("AGENT_OS_CONFIG", "config.yaml")

    try:
        from agentos_kernel.config import ConfigLoader
        cfg = ConfigLoader(app_config_path).load()
        host = cfg.adapters.feishu.listen_host if hasattr(cfg.adapters.feishu, "listen_host") else "0.0.0.0"
        port = cfg.adapters.feishu.listen_port if hasattr(cfg.adapters.feishu, "listen_port") else 8000
    except Exception:
        host = "0.0.0.0"
        port = 8000

    host = os.environ.get("AGENT_OS_HOST", host)
    port = int(os.environ.get("AGENT_OS_PORT", str(port)))

    logging.basicConfig(
        level=getattr(logging, os.environ.get("AGENT_OS_LOG_LEVEL", "INFO")),
        format="%(levelname)s  %(name)s  %(message)s",
    )

    logger.info("Starting Agent OS Unified Service on %s:%d ...", host, port)
    uvicorn.run(
        "agentos_main.main:app",
        host=host,
        port=port,
        reload=os.environ.get("AGENT_OS_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
