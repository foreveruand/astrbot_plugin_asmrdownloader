# ASMR Downloader Plugin for AstrBot

Download ASMR audio works from ASMR.ONE.

## Features

- Download ASMR audio works by RJ code
- Support HQ (lossless) audio only mode
- Blacklist filtering for unwanted tracks
- File organization with rclone support
- NFO metadata file generation
- VTT to LRC subtitle conversion
- dvtag integration for audio tagging
- Editable progress updates on supported platforms, with throttled fallback updates

## Installation

Install via AstrBot plugin marketplace or clone this repository to your `data/plugins/` directory.

## Usage

```
/asmr RJ123456
```

This command will:
1. Fetch work metadata from ASMR.ONE
2. Download selected audio tracks (HQ by default)
3. Download cover image
4. Apply dvtag for audio tagging
5. Convert VTT subtitles to LRC format
6. Organize files (if organizer_path is configured)

Progress updates are edited in place on supported platforms. On platforms without
message editing support, download and rclone progress messages are throttled to
reduce message noise.

## Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `save_path` | string | `data/asmr` | ASMR file save path |
| `organizer_path` | string | `""` | Normal work organization path |
| `r18_organizer_path` | string | `""` | R18 work organization path |
| `max_concurrent_downloads` | int | `3` | Maximum concurrent downloads |
| `enable_rclone` | bool | `false` | Enable rclone upload |
| `rclone_server` | string | `""` | rclone remote name |
| `hq_only` | bool | `true` | Download lossless quality only |
| `host_name` | string | `https://api.asmr-200.com` | ASMR.ONE API address |
| `blacklist` | array | `["无SE", "SE無", ...]` | Title blacklist keywords |

## Requirements

- Python 3.10+
- aiohttp
- aiofiles
- httpx
- dvtag (optional, for audio tagging)

## License

MIT License
