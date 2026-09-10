# Yawn Kiosk

A fullscreen video of a man standing idle, who yawns when someone walks up to a presence sensor. Every switch between idle and yawn happens only at precomputed, visually seamless cut points.

- [CLAUDE.md](CLAUDE.md): full build brief (architecture, phases, behaviour spec).
- [docs/setup.md](docs/setup.md): hardware answers and decisions so far.
- [docs/analysis-report.md](docs/analysis-report.md): latest analysis results (generated).

**Status:** Phase 0 (inventory). Everything runs on the dev PC; no Pi or sensor yet.

## Setup (dev PC)

```sh
brew install ffmpeg                      # ffmpeg + ffprobe must be on PATH
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-analysis.txt
```

## Analyse a clip

Put the source video in `assets/raw/` (gitignored, never modified), then:

```sh
.venv/bin/python -m analysis.pipeline assets/raw/<clip>.mp4
```

This runs probe → normalize → segment → report. Outputs go to `build/` (gitignored) and `docs/analysis-report.md`. The review images are in `build/preview/`.

The clip must **start still, yawn, and end in the same still pose**, with a locked camera. Resolution and frame rate don't matter. To use a different video, run the same command on the new file. The simulated preview video is written to `assets/preview/preview.mp4`; diagnostic images remain in `build/preview/`.

To run the PC player, use `./.venv/bin/python -m player.main --windowed --hud`. Hold `SPACE` or press `T` to simulate presence. Use `--fast-input` when testing repeated arrivals; it shortens the PC-only absence debounce and cooldown without changing the kiosk settings.

Steps can also run on their own:

| Command | Does |
|---|---|
| `python -m analysis.probe <clip>` | Metadata + sanity flags → `build/probe.json` |
| `python -m analysis.normalize <clip>` | 720×1280, source fps, no audio, lossless → `build/normalized/<clip>.mkv` |
| `python -m analysis.segment build/normalized/<clip>.mkv` | Still/yawn/still boundaries, drift and seam costs, previews → `build/segments.json` |
| `python -m analysis.report` | Renders `docs/analysis-report.md` |

All tunables live in [analysis/config.py](analysis/config.py).

## Scripts

### Analysis scripts

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

### Player scripts

| Script | Purpose |
|---|---|
| `player/main.py` | Run the fullscreen or windowed PC player. |
| `player/state_machine.py` | Control idle, entering, yawning, and exiting states. |
| `player/sensor.py` | Provide keyboard, scripted, debounced, and future GPIO inputs. |
| `player/frames.py` | Load the manifest and decode video frames. |
| `player/settings.py` | Load `player/config.toml`. |

Run the player on a Mac or PC with:

```sh
./.venv/bin/python -m player.main --windowed --hud --fast-input
```

Hold `SPACE` or press `T` to simulate someone arriving. Press `Q` or `Esc` to quit.

## Tests

```sh
.venv/bin/python -m pytest
```
