"""File organization logic for ASMR works."""

import asyncio
import datetime
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import aiofiles

from astrbot import logger

from .config import PluginConfig

TRANSFERRING_RE = re.compile(
    r"^(?:Transferring:\s*)?\*\s*(?P<file>.+?):\s*"
    r"(?P<percent>\d+(?:\.\d+)?)%\s*/\s*(?P<total>[^,]+)"
    r"(?:,\s*(?P<speed>[^,]+))?"
    r"(?:,\s*ETA\s*(?P<eta>.+))?$"
)
TRANSFERRING_RE_FALLBACK = re.compile(
    r"^(?:Transferring:\s*)?\*\s*(?P<file>.+?):\s*"
    r"(?P<percent>\d+(?:\.\d+)?)%\s*"
    r"(?:,\s*(?P<speed>[^,]+))?"
    r"(?:,\s*ETA\s*(?P<eta>.+))?$"
)
SUMMARY_PERCENT_RE = re.compile(r"(?P<percent>\d+(?:\.\d+)?)%")


@dataclass
class RcloneProgressState:
    """Normalized rclone progress snapshot."""

    kind: Literal["file", "summary"] = "summary"
    overall_percent: float | None = None
    transferred: str | None = None
    total: str | None = None
    speed: str | None = None
    eta: str | None = None
    current_file: str | None = None
    details: list[str] | None = None

    def is_meaningful(self) -> bool:
        return any(
            value
            for value in (
                self.overall_percent is not None,
                self.transferred,
                self.total,
                self.speed,
                self.eta,
                self.current_file,
                self.details,
            )
        )

    def format_message(self) -> str:
        """Format a compact progress message."""
        lines: list[str] = []
        if self.overall_percent is not None:
            lines.append(f"Overall progress: {self.overall_percent:.1f}%")

        if self.transferred and self.total:
            lines.append(f"Transferred: {self.transferred} / {self.total}")
        elif self.transferred:
            lines.append(f"Transferred: {self.transferred}")
        elif self.total:
            lines.append(f"Transferred: {self.total}")

        if self.speed:
            lines.append(f"Speed: {self.speed}")
        if self.eta:
            lines.append(f"ETA: {self.eta}")
        if self.current_file:
            lines.append(f"Current file: {self.current_file}")
        if self.details:
            lines.extend(self.details)

        return "\n".join(lines)


def _safe_decode_line(line: bytes | str) -> str:
    if isinstance(line, str):
        return line.strip()
    return line.decode("utf-8", errors="replace").strip()


def _extract_overall_percent(parts: Iterable[str]) -> float | None:
    for part in parts:
        match = SUMMARY_PERCENT_RE.search(part)
        if match:
            try:
                return float(match.group("percent"))
            except ValueError:
                continue
    return None


def parse_rclone_progress_line(line: str) -> RcloneProgressState | None:
    """Parse a single rclone line into a normalized progress snapshot."""
    if not line:
        return None

    state = RcloneProgressState()

    if line.startswith("Transferred:"):
        state.kind = "summary"
        parts = [part.strip() for part in line.split(",")]
        summary = parts[0]
        summary_payload = summary.removeprefix("Transferred:").strip()

        if "/" in summary_payload:
            transferred, total = [
                item.strip() for item in summary_payload.split("/", 1)
            ]
            state.transferred = transferred or None
            state.total = total or None
        elif summary_payload:
            state.transferred = summary_payload

        percent = _extract_overall_percent(parts[1:])
        if percent is None:
            percent = _extract_overall_percent([summary_payload])
        state.overall_percent = percent
        for part in parts[1:]:
            if part.endswith("/s"):
                state.speed = part
            elif part.startswith("ETA "):
                state.eta = part.removeprefix("ETA ").strip()
        return state if state.is_meaningful() else None

    current_match = TRANSFERRING_RE.match(line) or TRANSFERRING_RE_FALLBACK.match(line)
    if current_match:
        state.kind = "file"
        state.current_file = current_match.group("file").strip()
        try:
            state.overall_percent = float(current_match.group("percent"))
        except ValueError:
            state.overall_percent = None
        if current_match.groupdict().get("speed"):
            state.speed = current_match.group("speed").strip()
        if current_match.groupdict().get("eta"):
            state.eta = current_match.group("eta").strip()
        if current_match.groupdict().get("total"):
            state.total = current_match.group("total").strip()
        return state if state.is_meaningful() else None

    return None


async def organize_album(config: PluginConfig, work_dir: Path, meta: dict):
    """Organize downloaded ASMR work into target directory."""
    artist = meta.get("circle", {}).get("name", "Unknown")

    await generate_nfo(work_dir, meta)

    if meta["nsfw"]:
        target = Path(config.r18_organizer_path) / artist / meta["source_id"]
    else:
        target = Path(config.organizer_path) / artist / meta["source_id"]

    if config.enable_rclone:
        transfer_cmd = [
            "rclone",
            "move",
            f"{work_dir}",
            f"{config.rclone_server}:{str(target)}",
            "-P",
            "--stats=3s",
            "--metadata",
            "--no-traverse",
        ]
        process = await asyncio.create_subprocess_exec(
            *transfer_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        last_message = ""
        active_file: str | None = None
        async for line in process.stdout:
            decoded_line = _safe_decode_line(line)
            snapshot = parse_rclone_progress_line(decoded_line)
            if snapshot is None:
                continue

            if snapshot.current_file:
                active_file = snapshot.current_file

            if snapshot.kind == "file":
                continue

            if active_file and not snapshot.current_file:
                snapshot.current_file = active_file

            message = snapshot.format_message()
            if message == last_message:
                continue

            last_message = message
            yield "progress", message
        return_code = await process.wait()
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
