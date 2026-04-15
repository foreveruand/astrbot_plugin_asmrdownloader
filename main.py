"""ASMR Downloader Plugin for AstrBot.

Download ASMR audio works from ASMR.ONE.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot import logger
from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, filter

from .config import PluginConfig
from .downloader import process_work

RJ_RE = re.compile(r"(?:RJ)?(\d+)")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")

PROGRESS_STATUSES = {"update", "progress"}
FALLBACK_PROGRESS_INTERVAL_SECONDS = 60
FALLBACK_PROGRESS_PERCENT_STEP = 20


@dataclass
class DownloadResult:
    """Result of a download operation."""

    files: int
    size: float


class ProgressPublisher:
    """Publish progress with message editing where the platform supports it."""

    def __init__(self, event: AstrMessageEvent) -> None:
        self.event = event
        self._last_message = ""
        self._last_sent_at = 0.0
        self._last_percent: float | None = None
        self._last_phase = ""
        self._telegram_message: Any | None = None
        self._telegram_payload = self._build_telegram_payload()

    def _build_telegram_payload(self) -> dict[str, Any] | None:
        client = getattr(self.event, "client", None)
        if not client or not all(
            hasattr(client, attr) for attr in ("send_message", "edit_message_text")
        ):
            return None

        try:
            if self.event.is_private_chat():
                user_name = self.event.get_sender_id()
            else:
                user_name = self.event.message_obj.group_id
        except Exception as e:
            logger.debug(f"Failed to build editable message payload: {e}")
            return None

        if not user_name:
            return None

        message_thread_id = None
        if "#" in user_name:
            user_name, message_thread_id = user_name.split("#", 1)

        payload: dict[str, Any] = {"chat_id": user_name}
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id
        return payload

    @property
    def supports_edit(self) -> bool:
        return self._telegram_payload is not None

    async def publish_progress(self, phase: str, message: str) -> None:
        if not message or message == self._last_message:
            return

        if self.supports_edit:
            await self._edit_or_send(message)
            return

        if self._should_send_fallback(phase, message):
            await self._send(message)

    async def publish_terminal(self, message: str) -> None:
        if self.supports_edit and self._telegram_message:
            await self._edit_or_send(message)
        else:
            await self._send(message)

    async def send(self, message: str) -> None:
        await self._send(message)

    async def _send(self, message: str) -> None:
        self._last_message = message
        self._last_sent_at = time.monotonic()
        self._last_percent = self._extract_percent(message)
        await self.event.send(self.event.make_result().message(message))

    async def _edit_or_send(self, message: str) -> None:
        payload = self._telegram_payload
        client = getattr(self.event, "client", None)
        if not payload or not client:
            await self._send(message)
            return

        try:
            if self._telegram_message is None:
                self._telegram_message = await client.send_message(
                    text=message[:4096],
                    **payload,
                )
            else:
                await client.edit_message_text(
                    chat_id=payload["chat_id"],
                    message_id=self._telegram_message.message_id,
                    text=message[:4096],
                )
            self._last_message = message
            self._last_sent_at = time.monotonic()
            self._last_percent = self._extract_percent(message)
        except Exception as e:
            logger.warning(
                f"Editable progress update failed, falling back to send: {e}"
            )
            self._telegram_payload = None
            await self._send(message)

    def _should_send_fallback(self, phase: str, message: str) -> bool:
        now = time.monotonic()
        percent = self._extract_percent(message)

        if phase != self._last_phase:
            self._last_phase = phase
            self._last_percent = None
            return True

        if not self._last_sent_at:
            return True

        if now - self._last_sent_at >= FALLBACK_PROGRESS_INTERVAL_SECONDS:
            return True

        if percent is None:
            return False

        if self._last_percent is None:
            return True

        return percent >= self._last_percent + FALLBACK_PROGRESS_PERCENT_STEP or (
            percent >= 100 and self._last_percent < 100
        )

    @staticmethod
    def _extract_percent(message: str) -> float | None:
        match = re.search(r"Overall progress:\s*(\d+(?:\.\d+)?)%", message)
        if match:
            return float(match.group(1))

        values = [float(value) for value in PERCENT_RE.findall(message)]
        if not values:
            return None
        return max(values)


class Main(star.Star):
    """ASMR Downloader Plugin - Download ASMR works from ASMR.ONE."""

    author = "your-name"
    name = "astrbot_plugin_asmrdownloader"

    def __init__(self, context: star.Context, config: dict) -> None:
        self.context = context
        self.config = PluginConfig(**config) if config else PluginConfig()
        # Ensure save path exists
        Path(self.config.save_path).mkdir(parents=True, exist_ok=True)

    @filter.command("asmr")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def asmr(self, event: AstrMessageEvent, rj_code: str = "") -> None:
        """Download ASMR work by RJ code.

        Usage: /asmr RJ123456
        """
        # Parse RJ code
        m = RJ_RE.search(rj_code)
        if not m:
            event.set_result(event.plain_result("Usage: /asmr RJ123456"))
            return

        work_id = m.group(1)
        logger.info(f"Starting ASMR download for RJ{work_id}")

        # Start download task
        asyncio.create_task(self._run_asmr_task(event, work_id))

        event.set_result(event.plain_result(f"Starting download RJ{work_id}..."))

    async def _run_asmr_task(self, event: AstrMessageEvent, work_id: str) -> None:
        """Run the ASMR download task in background."""
        try:
            results = process_work(work_id, self.config)
            publisher = ProgressPublisher(event)
            async for status, result in results:
                try:
                    if status == "finished":
                        await publisher.publish_terminal(
                            f"RJ{work_id} download completed\n"
                            f"Files: {result.files}\n"
                            f"Size: {result.size:.2f} MB"
                        )
                    elif status == "success":
                        await publisher.send(result)
                    elif status in PROGRESS_STATUSES:
                        await publisher.publish_progress(status, result)
                    else:
                        await publisher.send(result)
                except Exception as e:
                    logger.error(f"Failed to send message: {e}")

        except Exception as e:
            logger.error(f"ASMR download failed for RJ{work_id}: {e}")
            await event.send(
                event.make_result().message(f"RJ{work_id} processing failed: {e}")
            )
