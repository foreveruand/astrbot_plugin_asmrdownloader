"""Download logic for ASMR works."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import aiofiles
import aiohttp
import httpx

from astrbot import logger

from .api import create_session, fetch_work_metadata, fetch_work_tracks
from .config import PluginConfig, WorkTrack
from .organizer import organize_album


@dataclass
class DownloadResult:
    """Result of a download operation."""

    files: int
    size: float


async def check_file_integrity(track: WorkTrack) -> bool:
    """Verify that the local file exists and matches the expected size when known."""
    if not track.save_path.exists():
        return False
    try:
        actual_size = track.save_path.stat().st_size
    except OSError:
        return False

    expected_bytes: int | None = None
    total_bytes = getattr(track, "total_bytes", None)
    if total_bytes is not None and total_bytes > 0:
        expected_bytes = int(total_bytes)
    elif getattr(track, "size", None) is not None:
        # track.size is stored in megabytes
        expected_bytes = int(float(track.size) * 1024 * 1024)

    if expected_bytes is None:
        # No reliable size information available; existence is the best check.
        return True
    return actual_size == expected_bytes


def is_text_track(track: WorkTrack) -> bool:
    """Return True when the track represents a text-like file."""
    return track.type == "text" or track.save_path.suffix.lower() in {
        ".txt",
        ".md",
        ".srt",
        ".vtt",
        ".lrc",
        ".ass",
        ".ssa",
    }


async def select_files_to_download(
    tracks: list[WorkTrack], config: PluginConfig, work_id: str
) -> list[WorkTrack]:
    """Select files to download based on config and blacklist."""
    if not tracks:
        logger.error("No files found to download.")
        return []

    selected_tracks = []
    allowed_types = {
        t.lower() for t in (config.default_file_types or []) if isinstance(t, str)
    }
    for track in tracks:
        # Check blacklist
        if any(banned in track.folder_path for banned in config.blacklist):
            continue
        if any(banned in track.filename for banned in config.blacklist):
            continue

        # Restrict to configured file types
        track_type = track.type.lower()
        if allowed_types and track_type not in allowed_types:
            continue

        if track_type == "audio":
            if config.hq_only and not track.is_hq():
                continue
            selected_tracks.append(track)
        else:
            selected_tracks.append(track)

    if not selected_tracks:
        logger.info(f"No files selected for RJ{work_id}. Skipping.")
        return []

    return selected_tracks


async def download_cover(
    session: aiohttp.ClientSession, cover_url: str, save_dir: Path
) -> Path | None:
    """Download cover image."""
    if not cover_url:
        return None
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = "cover.jpg"
    save_path = save_dir / filename
    try:
        async with session.get(cover_url, timeout=30) as resp:
            resp.raise_for_status()
            async with aiofiles.open(save_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    await f.write(chunk)
        return save_path
    except Exception as e:
        logger.error(f"Cover download failed: {e}")
        return None


def vtt_timestamp_to_lrc(ts: str) -> str:
    """Convert VTT timestamp to LRC format (ignoring milliseconds)."""
    # ts example: 00:00:14.180
    ts = ts.replace(",", ".")  # Handle 00:00:14,180 format
    parts = ts.split(":")
    if len(parts) != 3:
        return "[00:00]"

    h, m, s = parts
    if "." in s:
        s = s.split(".")[0]  # Remove milliseconds
    h, m, s = int(h), int(m), int(s)
    total_m = h * 60 + m
    return f"[{total_m:02d}:{s:02d}]"


def convert_vtt_to_lrc(vtt_path: Path, lrc_path: Path) -> None:
    """Convert VTT subtitle file to LRC format."""
    with open(vtt_path, encoding="utf-8-sig", errors="replace") as f:
        lines = f.readlines()

    lrc_lines = []
    for i, line in enumerate(lines):
        line = line.strip()
        if "-->" in line:  # Timestamp line
            ts = line.split("-->")[0].strip()
            lrc_time = vtt_timestamp_to_lrc(ts)
            if i + 1 < len(lines):
                text = lines[i + 1].strip()
                if text and not text.isdigit():
                    lrc_lines.append(f"{lrc_time}{text}")
            if i + 2 < len(lines):
                text = lines[i + 2].strip()
                if text and not text.isdigit():
                    lrc_lines.append(f"{text}")

    with open(lrc_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lrc_lines))


async def download_track(
    session: aiohttp.ClientSession,
    track: WorkTrack,
    track_index: int,
    max_concurrent_downloads: int,
    chunk_size: int,
) -> tuple[bool, float]:
    """Download a single track with retry logic."""
    if await check_file_integrity(track):
        track.status = "Downloaded"
        return True, (track.size or 0) / 1024 / 1024

    if track.status in ("Skipped", "Completed"):
        return True, (track.size or 0) / 1024 / 1024

    track.status = "Downloading"
    total_size = track.size or 0

    for attempt in range(3):
        try:
            logger.debug(
                f"Starting download: {track.filename} ({track_index + 1}/{max_concurrent_downloads})"
            )

            track.save_path.parent.mkdir(parents=True, exist_ok=True)

            existing_size = (
                track.save_path.stat().st_size if track.save_path.exists() else 0
            )
            headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "GET",
                    track.url,
                    headers=headers,
                    follow_redirects=True,
                ) as r:
                    if r.status_code == 416:
                        raise httpx.HTTPStatusError(
                            "Range Not Satisfiable", request=r.request, response=r
                        )

                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0))
                    content_range = r.headers.get("Content-Range")
                    if content_range and "/" in content_range:
                        total = int(content_range.rsplit("/", 1)[1])
                    track.total_bytes = total
                    if total and total_size == 0:
                        track.size = total / 1024 / 1024
                    should_resume = (
                        existing_size > 0
                        and r.status_code == 206
                        and bool(content_range)
                    )
                    if not should_resume and existing_size > 0:
                        try:
                            track.save_path.unlink()
                        except OSError:
                            pass
                        existing_size = 0

                    track.downloaded_bytes = existing_size if should_resume else 0
                    # Append only when the server actually honored the range request.
                    with open(track.save_path, "ab" if should_resume else "wb") as f:
                        async for chunk in r.aiter_bytes(chunk_size=chunk_size):
                            if not chunk:
                                continue
                            f.write(chunk)
                            track.downloaded_bytes += len(chunk)
                            if total:
                                track.progress = track.downloaded_bytes / total
                            else:
                                track.progress = None
                            # Avoid blocking event loop
                            await asyncio.sleep(0)

            track.status = "Completed"
            return True, track.downloaded_bytes / 1024 / 1024

        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 416:
                if attempt < 2:
                    track.status = "Retrying"
                    logger.warning(
                        f"Range request failed for {track.filename} with 416. "
                        "Re-downloading from scratch..."
                    )
                    try:
                        track.save_path.unlink()
                    except OSError:
                        pass
                    await asyncio.sleep(1)
                    continue
                track.status = "Error"
                logger.error(
                    f"Failed to download {track.filename}: {e}. "
                    "Server rejected resume requests."
                )
                return False, 0
            if attempt < 2:
                track.status = "Retrying"
                logger.error(
                    f"HTTP error downloading {track.filename}: {e}. "
                    f"Retrying ({attempt + 2}/3)..."
                )
                await asyncio.sleep(2)
            else:
                track.status = "Error"
                logger.error(f"Failed to download {track.filename}: {e}")
                return False, 0

        except Exception as e:
            if attempt < 2:
                track.status = "Retrying"
                logger.error(
                    f"Unexpected error downloading {track.filename}: {e}. "
                    f"Retrying ({attempt + 2}/3)..."
                )
                await asyncio.sleep(2)
            else:
                track.status = "Error"
                logger.error(f"Failed to download {track.filename}: {e}")
                return False, 0

    track.status = "Error"
    return False, 0


async def process_work(work_id: str, config: PluginConfig):
    """Process and download an ASMR work."""
    base_dir = Path(config.save_path)
    base_dir.mkdir(parents=True, exist_ok=True)

    async with create_session() as session:
        meta = await fetch_work_metadata(session, work_id, config)
        if not meta:
            raise Exception(f"Skipping RJ{work_id} due to metadata fetch failure.")

        tracks = await fetch_work_tracks(session, work_id, config)
        selected_tracks = await select_files_to_download(tracks, config, work_id)

        if not tracks:
            raise Exception(f"No tracks found for RJ{work_id}. Skipping.")

        retry_count = 0
        total_size = 0

        while retry_count < 3:  # Retry until all files are downloaded
            semaphore = asyncio.Semaphore(config.max_concurrent_downloads)

            async def limited_download(track, index):
                try:
                    async with semaphore:
                        success, size_mb = await download_track(
                            session,
                            track,
                            index,
                            config.max_concurrent_downloads,
                            config.chunk_size,
                        )
                        if success:
                            return track, True, size_mb
                        else:
                            return track, False, 0
                except Exception as e:
                    logger.error(f"Error in limited_download for {track.filename}: {e}")
                    return track, False, 0

            tasks = [
                asyncio.create_task(
                    limited_download(track, i % config.max_concurrent_downloads)
                )
                for i, track in enumerate(selected_tracks)
            ]

            def build_status_message(tracks: list) -> str:
                completed_files = [
                    t for t in tracks if t.status in ["Downloaded", "Completed"]
                ]
                downloading_files = [
                    t
                    for t in tracks
                    if t.status in ["Downloading", "Retrying"] and t.total_bytes
                ]
                pending_files = [t for t in tracks if t.status in ["Pending"]]
                total_bytes = sum(
                    t.total_bytes or (int(float(t.size) * 1024 * 1024) if t.size else 0)
                    for t in tracks
                )
                downloaded_bytes = sum(
                    (
                        t.total_bytes
                        or (int(float(t.size) * 1024 * 1024) if t.size else 0)
                    )
                    if t.status in ["Downloaded", "Completed"]
                    else t.downloaded_bytes
                    for t in tracks
                )
                overall_progress = (
                    downloaded_bytes * 100 / total_bytes if total_bytes else 0
                )

                lines = [
                    f"Overall progress: {overall_progress:.1f}%",
                    f"Completed files: {len(completed_files)} / {len(tracks)}",
                    *[
                        f"{t.filename} - {(t.downloaded_bytes * 100 / t.total_bytes):.1f}% "
                        f"({t.downloaded_bytes / 1024 / 1024:.2f}MB / {t.total_bytes / 1024 / 1024:.2f}MB)"
                        for t in downloading_files
                    ],
                    f"Pending files: {len(pending_files)}",
                ]
                return "\n".join(lines)

            pending = set(tasks)

            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=2, return_when=asyncio.FIRST_COMPLETED
                )

                # Periodic status update
                msg = build_status_message(selected_tracks)
                yield "update", msg

                # Process completed tasks
                for task in done:
                    track, success, size_mb = task.result()
                    if success:
                        total_size += size_mb
                    logger.debug(
                        f"download task finished: {track.filename} : {track.status}"
                    )

            finished = True
            logger.debug("all tasks finished, check all files")
            for track in selected_tracks:
                if not track.save_path.exists():
                    finished = False
                    logger.error(
                        f"File {track.filename} not found. Scheduling for retry."
                    )
                elif not await check_file_integrity(track):
                    finished = False
                    logger.error(
                        f"File {track.filename} size mismatch. Scheduling for retry."
                    )

            if finished:
                logger.debug("all tasks finished, and check pass. break the loop")
                break
            retry_count += 1

        # Final verification of downloaded files
        logger.debug(f"start to download cover of RJ{work_id}")
        await download_cover(session, meta["mainCoverUrl"], base_dir / f"RJ{work_id}")

        verified_downloaded = 0
        failed_files = []
        for track in tracks:
            if await check_file_integrity(track):
                verified_downloaded += 1
            elif track in selected_tracks:
                failed_files.append(track)

        non_text_failed_files = [
            track for track in failed_files if not is_text_track(track)
        ]
        if non_text_failed_files:
            raise Exception(
                f"Failed files for RJ{work_id}: "
                f"{[t.filename for t in non_text_failed_files]}"
            )

        if failed_files:
            logger.warning(
                f"Text files failed verification for RJ{work_id}, "
                "continuing processing: "
                f"{[t.filename for t in failed_files]}"
            )

        logger.debug(f"start dvtag process of RJ{work_id}")
        # dvtag
        process = await asyncio.create_subprocess_exec(
            "dvtag",
            "-w2f",
            str(base_dir / f"RJ{work_id}"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

        # Convert VTT to LRC
        vtt_dir = base_dir / f"RJ{work_id}"
        vtt_files = list(vtt_dir.rglob("*.vtt"))
        for path in vtt_files:
            if path.name.endswith(".wav.vtt"):
                lrc_path = path.with_name(path.name.removesuffix(".wav.vtt") + ".lrc")
            else:
                lrc_path = path.with_suffix(".lrc")

            convert_vtt_to_lrc(path, lrc_path)

        # Organize files
        async for transfer_finish, progress in organize_album(
            config, base_dir / f"RJ{work_id}", meta
        ):
            if transfer_finish == "success":
                yield "success", f"Transfer successful: {progress}"
            else:
                yield transfer_finish, f"Transfer progress: {progress}"

        yield "finished", DownloadResult(verified_downloaded, total_size)
