"""ASMR.ONE API client."""

import asyncio
import json
from pathlib import Path

import aiofiles
import aiohttp

from astrbot import logger

from .config import PluginConfig, WorkTrack

# Create cache directory
Path("data/asmr_downloader").mkdir(parents=True, exist_ok=True)


def transform_work_data(
    data: list[dict], base_folder: Path, parent_folder: str = ""
) -> list[WorkTrack]:
    """Transform API response data into WorkTrack objects."""
    if not data:
        return []
    current_data = []
    for item in data:
        folder_path = (
            f"{parent_folder}/{item['title']}" if parent_folder else item["title"]
        )
        match item["type"]:
            case "folder":
                folder_base = base_folder / item["title"]
                current_data.extend(
                    transform_work_data(item["children"], folder_base, folder_path)
                )
            case "text" | "image" | "audio":
                current_data.append(
                    WorkTrack(
                        filename=item["title"],
                        url=item["mediaDownloadUrl"],
                        type=item["type"],
                        save_path=base_folder / item["title"],
                        size=item.get("size"),
                        folder_path=parent_folder,
                    )
                )
    return current_data


async def fetch_work_tracks(
    session: aiohttp.ClientSession, work_id: str, config: PluginConfig
) -> list[WorkTrack]:
    """Fetch track list for a work from ASMR.ONE API."""
    base_dir = Path(config.save_path)
    cache_file = Path("data") / "asmr_downloader" / f"RJ{work_id}_tracks.json"

    # Try to load from cache
    if cache_file.exists():
        try:
            async with aiofiles.open(cache_file, encoding="utf-8") as f:
                data = json.loads(await f.read())
            logger.debug(f"Using cached tracks for RJ{work_id}")
        except Exception as e:
            logger.error(f"Error reading cache file for RJ{work_id}: {e}")
            data = None
    else:
        data = None

    # Fetch from API if no cache
    if not data:
        for attempt in range(3):
            try:
                async with session.get(
                    f"{config.host_name}/api/tracks/{work_id}?v=2", timeout=30
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    async with aiofiles.open(cache_file, "w", encoding="utf-8") as f:
                        await f.write(json.dumps(data))
                    logger.info(f"Successfully fetched tracks from {config.host_name}")
                    break
            except aiohttp.ClientError as e:
                if attempt < 2:
                    logger.error(
                        f"Error fetching tracks for RJ{work_id}: {e}. Retrying ({attempt + 2}/3)..."
                    )
                    await asyncio.sleep(2)
                else:
                    logger.error(
                        f"Failed to fetch tracks for RJ{work_id} after 3 attempts: {e}"
                    )
                    return []

    return transform_work_data(data, base_dir / f"RJ{work_id}")


async def fetch_work_metadata(
    session: aiohttp.ClientSession, work_id: str, config: PluginConfig
) -> dict:
    """Fetch metadata for a work from ASMR.ONE API."""
    for attempt in range(3):
        try:
            async with session.get(
                f"{config.host_name}/api/workInfo/{work_id}", timeout=30
            ) as response:
                response.raise_for_status()
                data = await response.json()
                logger.debug(f"Successfully fetched metadata from {config.host_name}")
                return data
        except aiohttp.ClientError as e:
            if attempt < 2:
                logger.error(
                    f"Error fetching metadata for RJ{work_id}: {e}. Retrying ({attempt + 2}/3)..."
                )
                await asyncio.sleep(2)
            else:
                logger.error(
                    f"Failed to fetch metadata for RJ{work_id} after 3 attempts: {e}"
                )
                return {}
    return {}


def create_session() -> aiohttp.ClientSession:
    """Create an aiohttp session with proper headers."""
    return aiohttp.ClientSession(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Origin": "https://asmr.one",
            "Referer": "https://asmr.one/",
            "Accept": "application/json",
        }
    )
