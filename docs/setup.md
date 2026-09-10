# Setup answers (brief, section 2)

Recorded 2026-09-10. Items marked *deferred* aren't needed while everything runs on the dev PC.

| # | Question | Answer |
|---|---|---|
| 1 | Pi model / RAM | Deferred. Development and testing run on the dev PC for now. |
| 2 | OS | Deferred. |
| 3 | Display | Deferred. The source clip is portrait (1080×1920), so the display needs to be mounted in portrait or the video letterboxed. |
| 4 | Sensor | Deferred. Presence is simulated on the PC (scripted / keyboard sensor); no GPIO work yet. |
| 5 | Videos | One clip holding both idle and yawn: `assets/raw/Man_yawning_on_white_background_202609071453.mp4` (still → yawn → still). Audio is not needed and is stripped. |
| 6 | Tripod / re-shoot | Camera is effectively locked. The clip can be reworked later; the pipeline re-runs on a new clip unchanged. |
| 7 | Where things run | Dev PC (macOS, Python 3.12 venv) for analysis and, later, the player. Pi access deferred. |

## Deviations from the brief

- **Single source clip** instead of separate idle and yawn clips. Idle frames come from the still start and end of the clip; `analysis/segment.py` (not in the brief) finds them.
- **Rejected clip:** `Man_yawning_in_studio_1080p_202609061536.mp4` starts mid-yawn (no onset to enter from) and the camera zooms/pans in its second half.
- **Frame rate stays at the source's 24 fps**; resampling to 30 would only add duplicate frames.
- **Normalised intermediates are FFV1 (lossless) `.mkv`** in `build/normalized/`.
- **All decoding goes through ffmpeg pipes** (`analysis/video_io.py`), so the analysis doesn't depend on which codecs a given OpenCV build ships with.
