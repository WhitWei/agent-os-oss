"""Abstract base class for channel adapters.

All channel adapters (Feishu, CLI, Slack, etc.) must implement this interface.
The kernel only depends on this ABC — never on concrete adapter types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentos_kernel.kernel import ChannelMessage, ChannelResponse


class ChannelAdapter(ABC):
    """Abstract base for all IM/shell channel adapters.

    Each adapter is responsible for:
    1. Receiving messages from its channel in channel-native format
    2. Parsing them into the normalized ChannelMessage dataclass
    3. Formatting and sending ChannelResponse back through the channel
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Unique name for this channel (e.g., 'feishu', 'cli', 'slack')."""

    @abstractmethod
    async def send_response(self, response: ChannelResponse) -> None:
        """Send a response back through the channel."""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming messages (if applicable)."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and clean up resources."""
