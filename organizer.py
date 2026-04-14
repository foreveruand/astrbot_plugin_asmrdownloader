"""File organization logic for ASMR works."""

import datetime
import shutil
from pathlib import Path

import aiofiles

from astrbot import logger

from .config import PluginConfig


async def organize_album(config: PluginConfig, work_dir: Path, meta: dict):
    """Organize downloaded ASMR work into target directory."""
    artist = meta.get("circle", {}).get("name", "Unknown")

    await generate_nfo(work_dir, meta)

    if meta["nsfw"]:
        target = Path(config.r18_organizer_path) / artist / meta["source_id"]
    else:
        target = Path(config.organizer_path) / artist / meta["source_id"]

    if config.enable_rclone:
        import subprocess

        transfer_cmd = [
            "rclone",
            "move",
            f"{work_dir}",
            f"{config.rclone_server}:{str(target)}",
            "-P",
            "--stats=2s",
            "--no-traverse",
        ]
        # Run rclone and yield progress
        process = subprocess.Popen(
            transfer_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in process.stdout or []:
            yield "progress", line.strip()
        return_code = process.wait()
        if return_code:
            raise RuntimeError(f"rclone failed with exit code {return_code}")
        yield "success", f"{str(work_dir)} -> {config.rclone_server}:{str(target)}"
    else:
        logger.info(f"asmr organizer path: {str(target)}")
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(work_dir), str(target))
            yield "success", f"{str(work_dir)} -> {str(target)}"
        else:
            logger.info(
                f"No organizer path configured, files remain at {str(work_dir)}"
            )
            yield "success", f"Files saved at {str(work_dir)}"


async def generate_nfo(save_dir: Path, work_metadata: dict):
    """Generate NFO metadata file for the ASMR work."""
    nfo_path = save_dir / "album.nfo"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    title = work_metadata.get("title", "Unknown Title")
    year = str(work_metadata.get("release", now))[:4]
    runtime = work_metadata.get("duration", 0) // 60  # Seconds to minutes
    maker = work_metadata.get("circle", {}).get("name", "")

    # genres from tags
    genres = [tag.get("name") for tag in work_metadata.get("tags", [])]
    genres_xml = "".join([f"  <genre>{g}</genre>\n" for g in genres])

    # artist and albumartist use circle.name
    vas_list = work_metadata.get("vas", [])
    artist_names = [vas.get("name", "Unknown") for vas in vas_list]
    if not artist_names:
        artist_names = ["Unknown"]

    artists_xml = "".join([f"  <artist>{name}</artist>\n" for name in artist_names])
    albumartists_xml = "".join(
        [f"  <albumartist>{name}</albumartist>\n" for name in artist_names]
    )

    cover_url = work_metadata.get("mainCoverUrl", "")

    nfo_content = f"""<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<album>
  <review />
  <outline />
  <lockdata>false</lockdata>
  <dateadded>{now}</dateadded>
  <title>{title}</title>
  <year>{year}</year>
  <sorttitle>{title}</sorttitle>
  <runtime>{runtime}</runtime>
{genres_xml.strip()}
{artists_xml.strip()}
{albumartists_xml.strip()}
  <maker>{maker}</maker>
  <thumb>{cover_url}</thumb>
</album>
"""
    async with aiofiles.open(nfo_path, "w", encoding="utf-8") as f:
        await f.write(nfo_content)
    return nfo_path
