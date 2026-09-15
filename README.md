# Yawn Kiosk

A fullscreen video of a man standing idle, who yawns when someone walks up to a presence sensor. Every switch between idle and yawn happens only at precomputed, visually seamless cut points.

- [CLAUDE.md](CLAUDE.md): full build brief (architecture, phases, behaviour spec).
- [docs/setup.md](docs/setup.md): hardware answers and decisions so far.
- [docs/analysis-report.md](docs/analysis-report.md): latest analysis results (generated).

**Status:** Analysis pipeline (Phase 2) and PC player (Phase 3) are built and approved. In progress: sensor bring-up (Phase 1) on a Pi 5 with a Waveshare HMMD mmWave sensor over UART ([docs/wiring.md](docs/wiring.md)). Then Pi deployment (Phase 4).

## Setup (dev PC)

```sh
brew install ffmpeg                      # ffmpeg + ffprobe must be on PATH
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-analysis.txt -r requirements-player.txt
```

## Analyse a clip

Put the source video in `assets/raw/` (gitignored, never modified), then:

```sh
.venv/bin/python -m analysis.pipeline assets/raw/<clip>.mp4
```

This runs probe → normalize → segment → export → preview → report. Outputs:

- `build/` (gitignored): normalised clip, `manifest.json`, bridge clips, and review images in `build/preview/`.
- `assets/preview/preview.mp4` (gitignored): simulated run with scripted arrivals.
- `docs/analysis-report.md`: cost tables, flags, and links to the review images.

The clip must **start still, yawn, and end in the same still pose**, with a locked camera. Resolution and frame rate don't matter. To use a different video, run the same command on the new file.

Steps can also run on their own:

| Command | Does |
|---|---|
| `python -m analysis.probe <clip>` | Metadata + sanity flags → `build/probe.json` |
| `python -m analysis.normalize <clip>` | 720×1280, source fps, no audio, lossless → `build/normalized/<clip>.mkv` |
| `python -m analysis.segment build/normalized/<clip>.mkv` | Still/yawn/still boundaries, drift and seam costs, previews → `build/segments.json` |
| `python -m analysis.export build/normalized/<clip>.mkv` | Idle loop, portals, bridge clips → `build/manifest.json` |
| `python -m analysis.preview` | Simulated run → `assets/preview/preview.mp4` + jump close-ups |
| `python -m analysis.report` | Renders `docs/analysis-report.md` |

All tunables live in [analysis/config.py](analysis/config.py).

## Run the player (PC)

```sh
.venv/bin/python -m player.main --windowed --hud --fast-input
```

Hold `SPACE` or press `T` to simulate someone arriving. Press `Q` or `Esc` to quit.

| Flag | Does |
|---|---|
| `--windowed` | Run in a window instead of fullscreen. |
| `--hud` | Show state, frame and presence in the corner. |
| `--fast-input` | Someone counts as gone 0.2 s after the sensor stops seeing them, and a new arrival counts once nobody has been there for 1.5 s (like the prototype's re-arm). Overrides `absence_off_s` and `cooldown_s` in `player/config.toml`. `deploy/run-pi.sh` turns it on. Arrivals during a yawn are always ignored. |
| `--sensor keyboard\|scripted\|hmmd\|gpio` | Where presence comes from. `keyboard` (default) is SPACE/T; `scripted` replays random visits for unattended soak tests; `hmmd` is the real mmWave sensor on the Pi (distance zone and serial port in `player/config.toml`, wiring in [docs/wiring.md](docs/wiring.md)); `gpio` is a plain on/off sensor output (unused fallback). |
| `--seed <n>` | Visit schedule for `--sensor scripted` (default 7). |
| `--frames auto\|surfaces\|jpeg` | How frames are kept in RAM. `surfaces` is fastest (just blitting); `jpeg` uses ~20× less memory and decodes one frame ahead in a worker thread. `auto` (default) picks `jpeg` only when Surfaces would exceed 60% of available RAM. |
| `--config <path>` | Use a different settings file (default `player/config.toml`). |

For a soak test: `.venv/bin/python -m player.main --sensor scripted` and watch the log for `behind schedule` warnings.

Behaviour and debounce settings are in [player/config.toml](player/config.toml).

## Run on the Raspberry Pi

1. Get the repo onto the Pi, e.g. `git clone`. That includes `build/manifest.json`. The video clips aren't in git (~90 MB), so copy them from the PC's repo root:
   ```sh
   rsync -av build/clips <user>@<pi-host>:<repo-on-pi>/build/
   ```
   **After every re-analysis, commit the new manifest and re-copy the clips.** The manifest's cut points are frame numbers in those exact clips, so a new manifest with old clips (or the reverse) gives visible jumps.
2. Wire the sensor and set up the serial port once: [docs/wiring.md](docs/wiring.md).
3. On the Pi, from the repo:
   ```sh
   deploy/run-pi.sh sensor-test   # live sensor readings, to check wiring
   deploy/run-pi.sh               # the kiosk: fullscreen, HMMD sensor
   ```

`deploy/run-pi.sh` installs any missing apt packages (`python3-pygame`, `python3-serial`, `ffmpeg`; asks for sudo only then). It checks the serial port, its permissions and the video files, and picks the display driver: desktop session, or KMS/DRM on OS Lite. It never edits boot configuration; if the serial port isn't set up, it prints the steps. The player runs with `--sensor hmmd --fast-input`. Extra arguments go to the player, e.g. `deploy/run-pi.sh --hud` or `deploy/run-pi.sh --sensor keyboard`. `deploy/run-pi.sh check` only installs and checks.

## Scripts

### Analysis

| Script | Purpose |
|---|---|
| `analysis/probe.py` | Read video metadata and report issues. |
| `analysis/normalize.py` | Convert a source clip to the analysis format. |
| `analysis/segment.py` | Find still, yawn, and still boundaries. |
| `analysis/features.py` | Build frame descriptors and motion distances. |
| `analysis/find_loop.py` | Select the idle loop and its seam. |
| `analysis/find_portals.py` | Select entry and exit transition points. |
| `analysis/bridges.py` | Generate pre-rendered crossfade frames. |
| `analysis/export.py` | Write bridge clips and `build/manifest.json`. |
| `analysis/preview.py` | Simulate arrivals and render the preview video. |
| `analysis/report.py` | Write `docs/analysis-report.md`. |
| `analysis/pipeline.py` | Run the complete analysis workflow. |

### Player

| Script | Purpose |
|---|---|
| `player/main.py` | Run the fullscreen or windowed player. |
| `player/state_machine.py` | Control idle, entering, yawning, and exiting states. |
| `player/sensor.py` | Sensor interface, debouncing, and GPIO, keyboard and scripted sensors. |
| `player/hmmd.py` | Waveshare HMMD mmWave sensor over UART: frame parser, distance zone, background reader. |

### Tools

| Script | Purpose |
|---|---|
| `tools/sensor_test.py` | Pi only: `python3 -m tools.sensor_test` prints live presence, distance and zone readings, for wiring bring-up. See [docs/wiring.md](docs/wiring.md). |
| `player/frames.py` | Load the manifest and keep frames in RAM (Surfaces, or JPEG with decode-ahead). |
| `player/settings.py` | Load `player/config.toml`. |

## Tests

```sh
.venv/bin/python -m pytest
```
