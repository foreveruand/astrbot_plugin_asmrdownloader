# Changelog

## 1.0.4

- Keep rclone progress updates on summary lines so messages stay stable and include the active file context.
- Keep dvtag as the primary tagging step and backfill missing FLAC metadata with Mutagen when dvtag does not write it.
- Embed cover art and basic album tags before rclone transfer so remote copies keep the metadata.

## 1.0.3

- Parse rclone output into compact progress snapshots instead of forwarding raw lines.
- Keep rclone progress updates aligned with download progress handling on editable and non-editable platforms.

## 1.0.2

- Recover from HTTP 416 resume failures by restarting the affected download from scratch.
- Allow text-only verification failures to continue the workflow with a warning.

## 1.0.1

- Use editable progress updates on supported platforms.
- Throttle download and rclone progress messages on platforms without message editing support.
- Tolerate non-UTF-8 bytes in VTT subtitle conversion and rclone output.
