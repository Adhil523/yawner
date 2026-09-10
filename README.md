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

The clip must **start still, yawn, and end in the same still pose**, with a locked camera. Resolution and frame rate don't matter. To use a different video, run the same command on the new file.

Steps can also run on their own:

| Command | Does |
|---|---|
| `python -m analysis.probe <clip>` | Metadata + sanity flags → `build/probe.json` |
| `python -m analysis.normalize <clip>` | 720×1280, source fps, no audio, lossless → `build/normalized/<clip>.mkv` |
| `python -m analysis.segment build/normalized/<clip>.mkv` | Still/yawn/still boundaries, drift and seam costs, previews → `build/segments.json` |
| `python -m analysis.report` | Renders `docs/analysis-report.md` |

All tunables live in [analysis/config.py](analysis/config.py).

## Tests

```sh
.venv/bin/python -m pytest
```
