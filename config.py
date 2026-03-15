"""Configuration models for ASMR Downloader Plugin."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class WorkTrack:
    """Represents a track/file in an ASMR work."""

    filename: str
    url: str
    type: Literal["folder", "text", "image", "audio"]
    save_path: Path
    size: int | None = None
    folder_path: str = ""  # Store folder hierarchy
    status: str = "Pending"  # Track download status
    downloaded_bytes: int = 0
    total_bytes: int = 0
    progress: float = 0.0

    def is_hq(self) -> bool | None:
        """Check if this is a high-quality audio file."""
        if self.type != "audio":
            return None
        return self.filename.endswith(".flac") or self.filename.endswith(".wav")


@dataclass
class PluginConfig:
    """Plugin configuration."""

    save_path: str = "data/asmr"
    """ASMR file save path"""

    organizer_path: str = ""
    """Normal work organization path"""

    r18_organizer_path: str = ""
    """R18 work organization path"""

    max_concurrent_downloads: int = 3
    """Maximum concurrent downloads"""

    enable_rclone: bool = False
    """Enable rclone upload"""

    rclone_server: str = ""
    """rclone remote name"""

    hq_only: bool = True
    """Download lossless quality only"""

    host_name: str = "https://api.asmr-200.com"
    """ASMR.ONE API address"""

    default_file_types: list[str] = field(
        default_factory=lambda: ["audio", "image", "text"]
    )
    """Default file types to download"""

    chunk_size: int = 8 * 1024 * 1024
    """Download chunk size"""

    blacklist: list[str] = field(
        default_factory=lambda: [
            "无SE",
            "SE無",
            "无音效",
            "効果音無し",
            "なし",
            "音效cut",
            "体験版",
        ]
    )
    """Title blacklist keywords"""
