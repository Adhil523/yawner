# Setup answers (brief, section 2)

Recorded 2026-09-10. Items marked *deferred* aren't needed while everything runs on the dev PC.

| # | Question | Answer |
|---|---|---|
| 1 | Pi model / RAM | Raspberry Pi 5 (confirmed 2026-09-15). RAM possibly 4 GB, unconfirmed; check with `free -h`. |
| 2 | OS | Unknown. Confirm with `cat /etc/os-release`. |
| 3 | Display | Deferred. The source clip is portrait (1080×1920), so the display needs to be mounted in portrait or the video letterboxed. |
| 4 | Sensor | Waveshare HMMD Human Micro-Motion Detection 24 GHz mmWave (S3KM1110), 3.3V, read over UART on a Pi 5 (`/dev/ttyAMA0`). Confirmed 2026-09-15 from the working prototype `~/Downloads/yawn-signage`. Wiring: [wiring.md](wiring.md). |
| 5 | Videos | One clip holding both idle and yawn: `assets/raw/Man_yawning_on_white_background_202609071453.mp4` (still → yawn → still). Audio is not needed and is stripped. |
| 6 | Tripod / re-shoot | Camera is effectively locked. The clip can be reworked later; the pipeline re-runs on a new clip unchanged. |
| 7 | Where things run | Dev PC (macOS, Python 3.12 venv) for analysis and, later, the player. Pi access deferred. |

## Deviations from the brief

- **Sensor over UART instead of a GPIO on/off pin** (approved 2026-09-15). The HMMD reports presence *and distance*; `player/hmmd.py` turns that into presence within a distance zone (`min_cm`/`max_cm`/`rearm_cm` in `player/config.toml`), so people passing further away don't trigger. The frame parser, report-mode command and Pi 5 serial setup are reused from the prototype. Its mpv player and trigger logic are not reused: the brief needs frame-exact playback, and our debounce and state machine already cover triggering.
- **Single source clip** instead of separate idle and yawn clips. Idle frames come from the still start and end of the clip; `analysis/segment.py` (not in the brief) finds them.
- **Rejected clip:** `Man_yawning_in_studio_1080p_202609061536.mp4` starts mid-yawn (no onset to enter from) and the camera zooms/pans in its second half.
- **Frame rate stays at the source's 24 fps**; resampling to 30 would only add duplicate frames.
- **Normalised intermediates are FFV1 (lossless) `.mkv`** in `build/normalized/`.
- **All decoding goes through ffmpeg pipes** (`analysis/video_io.py`), so the analysis doesn't depend on which codecs a given OpenCV build ships with.
