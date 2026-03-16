"""ASMR Downloader Plugin for AstrBot.

Download ASMR audio works from ASMR.ONE.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from astrbot import logger
from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, filter

from .config import PluginConfig
from .downloader import process_work

RJ_RE = re.compile(r"(?:RJ)?(\d+)")


@dataclass
class DownloadResult:
    """Result of a download operation."""

    files: int
    size: float


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
            last_message = ""
            async for status, result in results:
                try:
                    if status == "finished":
                        await event.send(
                            event.make_result().message(
                                f"RJ{work_id} download completed\n"
                                f"Files: {result.files}\n"
                                f"Size: {result.size:.2f} MB"
                            )
                        )
                    elif status == "success":
                        await event.send(event.make_result().message(result))
                    else:
                        # Skip duplicate messages
                        if last_message == result:
                            continue
                        last_message = result
                        await event.send(event.make_result().message(result))
                except Exception as e:
                    logger.error(f"Failed to send message: {e}")

        except Exception as e:
            logger.error(f"ASMR download failed for RJ{work_id}: {e}")
            await event.send(
                event.make_result().message(f"RJ{work_id} processing failed: {e}")
            )
