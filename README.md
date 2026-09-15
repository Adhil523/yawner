# Yawn Kiosk

A fullscreen video of a man standing idle, who yawns when someone walks up to a presence sensor. Every switch between idle and yawn happens only at precomputed, visually seamless cut points.

- [CLAUDE.md](CLAUDE.md): full build brief (architecture, phases, behaviour spec).
- [docs/setup.md](docs/setup.md): hardware answers and decisions so far.
- [docs/analysis-report.md](docs/analysis-report.md): latest analysis results (generated).

**Status:** Analysis pipeline (Phase 2) and PC player (Phase 3) are built and approved. Next: sensor wiring (Phase 1, deferred until hardware arrives) and Pi deployment (Phase 4). Everything currently runs on the dev PC with a keyboard-simulated sensor.

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
| `--fast-input` | PC testing only: shortens the absence debounce and cooldown so arrivals can be repeated quickly. Kiosk settings are unchanged. |
| `--sensor keyboard\|scripted` | Where presence comes from. `keyboard` (default) is SPACE/T; `scripted` replays random visits for unattended soak tests. `gpio` comes with the sensor wiring (Phase 1). |
| `--seed <n>` | Visit schedule for `--sensor scripted` (default 7). |
| `--frames auto\|surfaces\|jpeg` | How frames are kept in RAM. `surfaces` is fastest (just blitting); `jpeg` uses ~20× less memory and decodes one frame ahead in a worker thread. `auto` (default) picks `jpeg` only when Surfaces would exceed 60% of available RAM. |
| `--config <path>` | Use a different settings file (default `player/config.toml`). |

For a soak test: `.venv/bin/python -m player.main --sensor scripted` and watch the log for `behind schedule` warnings.

Behaviour and debounce settings are in [player/config.toml](player/config.toml).

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
| `player/sensor.py` | Keyboard and scripted sensors, and debouncing (GPIO sensor comes with Phase 1). |
| `player/frames.py` | Load the manifest and keep frames in RAM (Surfaces, or JPEG with decode-ahead). |
| `player/settings.py` | Load `player/config.toml`. |

## Tests

```sh
.venv/bin/python -m pytest
```
