"""Feishu (Lark) bot webhook channel adapter.

Handles:
- Webhook URL challenge verification (respond within 1 second)
- Event parsing (message received, mentions, etc.)
- Message reply via Lark API SDK
- Event decryption (if encryption is enabled)
- Interactive Card 审批卡片发送 (send_approval_card) — WO-A3.1
- Interactive Card 回调解析 (parse_card_callback) — 用于 HITL 审批

For local dev without Feishu credentials, set `enabled: false` in config.yaml
and use the CLIAdapter instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import httpx
from zeroclaw.config import FeishuAdapterConfig
from zeroclaw.kernel import ChannelMessage, ChannelResponse
from adapters.base import ChannelAdapter

logger = logging.getLogger(__name__)


class FeishuAdapter(ChannelAdapter):
    """Feishu (Lark) bot webhook adapter.

    Handles the Feishu Event Subscription protocol:
    - URL verification (challenge)
    - Event parsing (im.message.receive_v1)
    - Message reply via Send Message API
    """

    LARK_API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, config: FeishuAdapterConfig, message_handler=None) -> None:
        self._config = config
        self._message_handler = message_handler  # async callable(ChannelMessage) -> ChannelResponse
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ── ChannelAdapter Interface ──

    @property
    def channel_name(self) -> str:
        return "feishu"

    async def send_response(self, response: ChannelResponse) -> None:
        """Send a text message reply via Lark API."""
        if not response.metadata.get("feishu_message_id"):
            logger.warning("No feishu_message_id in response metadata — cannot reply")
            return

        msg_id = response.metadata["feishu_message_id"]
        await self._send_text_message(msg_id, response.text)

    async def start(self) -> None:
        """Start the webhook server (implemented via FastAPI in the API layer)."""
        logger.info("Feishu adapter ready (webhook path: %s)", self._config.webhook_path)

    async def stop(self) -> None:
        """Clean up HTTP client resources."""
        logger.info("Feishu adapter stopped")

    # ── Webhook Handlers (called from FastAPI route) ──

    def verify_challenge(self, body: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Handle Feishu URL verification challenge.

        Feishu sends a POST with `{"challenge": "...", "token": "..."}`.
        We must respond with `{"challenge": "..."}` within 1 second.

        Returns:
            Challenge response dict, or None if this is not a challenge request.
        """
        challenge = body.get("challenge")
        if challenge:
            token = body.get("token", "")
            event_type = body.get("type", "")
            logger.info("URL challenge received (type=%s, token=%s...)", event_type, token[:8])
            return {"challenge": challenge}
        return None

    def verify_signature(self, timestamp: str, nonce: str, body: str, expected_signature: str = "") -> bool:
        """Verify the Feishu event signature using HMAC-SHA256.

        Feishu signs each event with the verification_token. The signature
        is computed as SHA256(timestamp + nonce + verification_token + body).
        We compare against the signature from the X-Lark-Signature header using
        constant-time comparison to prevent timing attacks.

        Args:
            timestamp: From X-Lark-Request-Timestamp header.
            nonce: From X-Lark-Request-Nonce header.
            body: Raw HTTP request body bytes (decoded to str).
            expected_signature: From X-Lark-Signature header.

        Returns:
            True if signature matches, False otherwise.
        """
        if not self._config.verification_token:
            logger.error("No verification_token configured — signature verification FAILED")
            return False

        if not expected_signature:
            logger.warning("No signature provided in request header — rejected")
            return False

        if not timestamp or not nonce:
            logger.warning("Missing timestamp or nonce in request headers — rejected")
            return False

        payload = f"{timestamp}{nonce}{self._config.verification_token}{body}"
        computed = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(computed, expected_signature):
            logger.warning("Feishu signature verification FAILED — request rejected")
            return False

        logger.debug("Feishu signature verified successfully")
        return True

    def parse_event(self, event_body: dict[str, Any]) -> Optional[ChannelMessage]:
        """Parse a Feishu event into a normalized ChannelMessage.

        Supported event types:
        - im.message.receive_v1: User sends a message to the bot
        """
        event_header = event_body.get("header", {})
        event_type = event_header.get("event_type", "")
        event = event_body.get("event", {})

        if event_type == "im.message.receive_v1":
            return self._parse_im_message(event)
        else:
            logger.debug("Unhandled event type: %s", event_type)
            return None

    def _parse_im_message(self, event: dict[str, Any]) -> Optional[ChannelMessage]:
        """Parse an IM message receive event."""
        message = event.get("message", {})
        sender = event.get("sender", {})

        # Extract text content
        content_str = message.get("content", "{}")
        try:
            content = json.loads(content_str)
        except json.JSONDecodeError:
            content = {}

        text = content.get("text", "")

        # Skip messages without text
        if not text:
            return None

        return ChannelMessage(
            text=text,
            sender_id=sender.get("sender_id", {}).get("user_id", "unknown"),
            sender_name=sender.get("sender_id", {}).get("open_id", "unknown"),
            channel="feishu",
            message_id=message.get("message_id", ""),
            metadata={
                "feishu_message_id": message.get("message_id", ""),
                "feishu_chat_id": message.get("chat_id", ""),
                "feishu_message_type": message.get("message_type", "text"),
            },
        )

    # ── Lark API Helpers ──

    async def _get_tenant_access_token(self) -> Optional[str]:
        """Obtain or refresh the tenant access token."""
        if self._tenant_access_token and time.time() < self._token_expires_at - 60:
            return self._tenant_access_token

        if not self._config.app_id or not self._config.app_secret:
            logger.warning("Feishu app_id/app_secret not configured — cannot get token")
            return None

        url = f"{self.LARK_API_BASE}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self._config.app_id,
            "app_secret": self._config.app_secret,
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, timeout=10.0)
                resp.raise_for_status()
                data = resp.json()
                self._tenant_access_token = data.get("tenant_access_token")
                expire = data.get("expire", 7200)
                self._token_expires_at = time.time() + expire
                return self._tenant_access_token
            except Exception as exc:
                logger.error("Failed to get tenant access token: %s", exc)
                return None

    async def _send_text_message(self, message_id: str, text: str) -> bool:
        """Reply to a message via the Lark API."""
        token = await self._get_tenant_access_token()
        if not token:
            logger.warning("Cannot send message — no access token")
            return False

        url = f"{self.LARK_API_BASE}/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "content": json.dumps({"text": text}),
            "msg_type": "text",
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, headers=headers, json=payload, timeout=10.0)
                resp.raise_for_status()
                logger.info("Reply sent to message %s", message_id)
                return True
            except Exception as exc:
                logger.error("Failed to send reply: %s", exc)
                return False

    # ── Interactive Card: 审批卡片发送与回调解析 (WO-A3.1) ──

    async def send_approval_card(
        self,
        chat_id: str,
        title: str,
        message: str,
        run_id: str,
        card_payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """向指定飞书群/用户会话发送交互式审批卡片。

        卡片包含"批准"和"驳回"两个按钮，value 中携带 run_id 以便回调定位 SOP 实例。

        Args:
            chat_id: 目标会话 ID（群 chat_id 或用户 open_id）。
            title: 卡片标题（用于日志记录）。
            message: 卡片主体文本（用于日志，实际内容在 card_payload 中）。
            run_id: SOP 运行实例 ID，嵌入卡片按钮 value 中，供回调识别。
            card_payload: 完整的 Feishu Card JSON（由 build_approval_card 生成）。

        Returns:
            True 表示发送成功，False 表示失败（降级为日志记录，不中断流程）。
        """
        token = await self._get_tenant_access_token()
        if not token:
            logger.warning("[send_approval_card] 无访问令牌，跳过发送 (run_id=%s)", run_id)
            return False

        if not chat_id:
            logger.warning("[send_approval_card] chat_id 为空，跳过发送 (run_id=%s)", run_id)
            return False

        url = f"{self.LARK_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # NOTE: card_payload 应为 build_approval_card() 返回的字典
        payload_json = json.dumps(card_payload) if card_payload else json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": message}}],
        })

        req_body = {
            "receive_id": chat_id,
            "content": payload_json,
            "msg_type": "interactive",
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    json=req_body,
                    params={"receive_id_type": "chat_id"},
                    timeout=10.0,
                )
                resp.raise_for_status()
                logger.info(
                    "[send_approval_card] 审批卡片已发送 (chat=%s, run_id=%s)",
                    chat_id, run_id,
                )
                return True
            except Exception as exc:
                logger.error("[send_approval_card] 发送失败: %s", exc)
                return False

    def parse_card_callback(
        self, body: dict[str, Any]
    ) -> Optional[dict[str, str]]:
        """解析飞书 Interactive Card 按钮点击回调事件。

        当用户在审批卡片上点击"批准"或"驳回"时，飞书向 Webhook 发送 POST。
        此方法提取关键字段并返回结构化结果供 SOPEngine.resume() 使用。

        回调体关键字段（Feishu Card Action 规范）：
            {
                "open_id": "ou_xxx",            # 点击用户 ID
                "action": {
                    "value": {
                        "action": "APPROVED" | "REJECTED",
                        "run_id": "...",         # SOP 运行 ID
                        "step_id": "..."         # 触发审批的步骤 ID
                    },
                    "input": "审批意见文本"       # 若卡片含输入框
                }
            }

        Args:
            body: 飞书发来的原始回调 JSON dict。

        Returns:
            包含 run_id, step_id, decision, reviewer, reason 的 dict；
            若不是有效的审批回调则返回 None。
        """
        action_block = body.get("action", {})
        value = action_block.get("value", {})

        run_id = value.get("run_id", "")
        decision = value.get("action", "")   # 'APPROVED' | 'REJECTED'
        step_id = value.get("step_id", "")

        # 审批理由来自输入框或选项（卡片设计决定哪个字段携带文本）
        reason = action_block.get("input", "") or action_block.get("option", "")
        reviewer = body.get("open_id", "unknown")

        if not run_id or decision not in ("APPROVED", "REJECTED"):
            logger.debug("[parse_card_callback] 非审批回调，忽略")
            return None

        logger.info(
            "[parse_card_callback] 收到审批: run_id=%s, decision=%s, reviewer=%s",
            run_id, decision, reviewer,
        )
        return {
            "run_id": run_id,
            "step_id": step_id,
            "decision": decision,
            "reviewer": reviewer,
            "reason": reason,
        }
