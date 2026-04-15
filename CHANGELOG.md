# Changelog

## 1.0.2

- Recover from HTTP 416 resume failures by restarting the affected download from scratch.
- Allow text-only verification failures to continue the workflow with a warning.

## 1.0.1

- Use editable progress updates on supported platforms.
- Throttle download and rclone progress messages on platforms without message editing support.
- Tolerate non-UTF-8 bytes in VTT subtitle conversion and rclone output.
