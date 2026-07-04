"""CLI adapter for local development and debugging.

Reads messages from stdin (or accepts them programmatically) and writes
responses to stdout. Always enabled — no API keys needed.
"""

from __future__ import annotations

import logging

from agentos.kernel.kernel import ChannelMessage, ChannelResponse
from agentos.adapters.base import ChannelAdapter

logger = logging.getLogger(__name__)


class CLIAdapter(ChannelAdapter):
    """Simple CLI-based channel adapter for local development.

    Usage:
        adapter = CLIAdapter()
        msg = ChannelMessage(text="...", sender_id="dev", sender_name="Developer", channel="cli")
        response = await kernel.wake_up(msg)
        await adapter.send_response(response)
    """

    @property
    def channel_name(self) -> str:
        return "cli"

    async def send_response(self, response: ChannelResponse) -> None:
        """Print the response to stdout."""
        prefix = "❌" if response.error else "✅"
        print(f"\n{prefix} [{response.channel}] {response.text}")
        if response.metadata:
            print(f"   📎 metadata: {response.metadata}")

    async def start(self) -> None:
        logger.info("CLI adapter ready — accepting messages programmatically")

    async def stop(self) -> None:
        logger.info("CLI adapter stopped")
