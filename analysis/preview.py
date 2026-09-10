"""Simulated-arrival preview (brief 2i).

    python -m analysis.preview [--seconds 75] [--seed 7] [--no-overlay]

Drives the real player state machine (player/state_machine.py) with a scripted
sensor, using the kiosk's own debounce and behaviour settings from
player/config.toml, and renders what the screen would show to
build/preview/preview.mp4. Also draws a close-up sheet for every crossfade and
writes build/preview/preview.json for the report.
"""

import argparse
import json
import logging
import random
import sys
from typing import Any

import cv2
import numpy as np

from analysis import config
from analysis.cli import repo_relative, setup_logging
from analysis.features import scaled_size
from analysis.video_io import H264_ARGS, VideoToolError, VideoWriter, read_frames
from analysis.visuals import BGR, contact_sheet, difference_strip, label, rgb_to_bgr, save_png, stack_vertical
from player.sensor import Debouncer, ScriptedSensor
from player.settings import load_settings
from player.state_machine import MAIN, Graph, Jump, Phase, YawnStateMachine

log = logging.getLogger("preview")

PREVIEW_VIDEO = config.VIDEO_PREVIEW_DIR / "preview.mp4"
CONTEXT_FRAMES = 3
TILE_LONG_SIDE = 256
DIFF_LONG_SIDE = 640
DIFF_GAIN = 8.0
MAIN_COLOR: BGR = (130, 130, 130)
BRIDGE_COLOR: BGR = (0, 170, 255)


def random_visits(seconds: float, seed: int, absence_off_s: float, cooldown_s: float) -> list[tuple[float, float]]:
    """(arrive, leave) times, spaced so every visit gets past debounce and cooldown."""
    rng = random.Random(seed)
    visits: list[tuple[float, float]] = []
    arrive = 2.0
    while True:
        leave = arrive + rng.uniform(1.0, 6.0)
        if leave > seconds - 12.0:  # leave room for the last yawn to finish
            return visits
        visits.append((round(arrive, 2), round(leave, 2)))
        arrive = leave + absence_off_s + cooldown_s + rng.uniform(0.5, 4.0)


def load_sequences(manifest: dict[str, Any]) -> dict[str, np.ndarray]:
    width, height = manifest["resolution"]
    sequences = {}
    for name, sequence in manifest["sequences"].items():
        frames = read_frames(config.BUILD_DIR / sequence["file"], width, height)
        if len(frames) != sequence["frames"]:
            raise ValueError(f"{name}: manifest says {sequence['frames']} frames, file has {len(frames)}")
        sequences[name] = frames
    return sequences


def jump_sheet(sequences: dict[str, np.ndarray], jump: Jump) -> np.ndarray:
    """What the viewer sees around a crossfade, and below it the hard cut it replaces."""
    main = sequences[MAIN]
    height, width = main.shape[1:3]
    before = [i for i in range(jump.at - CONTEXT_FRAMES + 1, jump.at + 1) if i >= 0]
    after = [i for i in range(jump.resume, jump.resume + CONTEXT_FRAMES) if i < len(main)]
    shown = [(MAIN, i) for i in before] + [(str(jump.bridge), i) for i in range(jump.length)] + [(MAIN, i) for i in after]

    tile_size = scaled_size(width, height, TILE_LONG_SIDE)
    tiles = np.stack([cv2.resize(sequences[name][i], tile_size, interpolation=cv2.INTER_AREA) for name, i in shown])
    labels = [f"{'main' if name == MAIN else 'fade'} {i}" for name, i in shown]
    colors = [MAIN_COLOR if name == MAIN else BRIDGE_COLOR for name, _ in shown]
    row = contact_sheet(rgb_to_bgr(tiles), labels, colors, columns=len(shown))

    diff_size = scaled_size(width, height, DIFF_LONG_SIDE)
    cut_from, cut_to = jump.at + jump.length, jump.resume
    strip = difference_strip(
        rgb_to_bgr(cv2.resize(main[cut_from], diff_size, interpolation=cv2.INTER_AREA)),
        rgb_to_bgr(cv2.resize(main[cut_to], diff_size, interpolation=cv2.INTER_AREA)),
        DIFF_GAIN,
        (f"main {cut_from}", f"main {cut_to}", f"hard-cut |difference| x{DIFF_GAIN:g}"),
    )
    return stack_vertical([row, strip])


def _overlay(frame: np.ndarray, machine: YawnStateMachine, present: bool) -> np.ndarray:
    text = f"{machine.phase.value.upper()}   person: {'yes' if present else 'no'}"
    if machine.armed:
        text += "   armed"
    annotated = frame.copy()
    label(annotated, text, (12, 12), scale=0.8)
    return annotated


def run(seconds: float = config.PREVIEW_SECONDS, seed: int = config.PREVIEW_SEED, overlay: bool = True) -> dict[str, Any]:
    if not config.MANIFEST_JSON.is_file():
        raise ValueError(f"{repo_relative(config.MANIFEST_JSON)} missing; run analysis.export first")
    manifest = json.loads(config.MANIFEST_JSON.read_text())
    settings = load_settings()
    graph = Graph.from_manifest(manifest)
    fps = float(manifest["fps"])
    width, height = manifest["resolution"]
    sequences = load_sequences(manifest)

    visits = random_visits(seconds, seed, settings.sensor.absence_off_s, settings.behaviour.cooldown_s)
    events = [(0.0, False)] + [event for arrive, leave in visits for event in ((arrive, True), (leave, False))]
    sensor = ScriptedSensor(events)
    debouncer = Debouncer(settings.sensor.presence_on_s, settings.sensor.absence_off_s)
    machine = YawnStateMachine(graph, settings.behaviour)

    yawns: list[dict[str, Any]] = []
    jump_counts: dict[str, int] = {}
    with VideoWriter(PREVIEW_VIDEO, width, height, manifest["frame_rate"], H264_ARGS) as writer:
        for tick in range(round(seconds * fps)):
            now = tick / fps
            present = debouncer.update(sensor.raw(now), now)
            name, index = machine.current
            frame = sequences[name][index]
            writer.write(_overlay(frame, machine, present) if overlay else frame)

            before = machine.phase
            machine.advance(present, now)
            shown_at = (tick + 1) / fps  # when the frame just chosen appears
            jump = machine.last_jump
            if jump is not None:
                key = jump.bridge or f"straight on {jump.at}->{jump.resume}"
                jump_counts[key] = jump_counts.get(key, 0) + 1
                if jump in graph.entries:
                    yawns.append({"entry_s": round(shown_at, 3), "cut": f"{jump.at}->{jump.resume}"})
            if before is not Phase.YAWNING and machine.phase is Phase.YAWNING and yawns:
                yawns[-1]["yawn_start_s"] = round(shown_at, 3)

    starts = [yawn["yawn_start_s"] for yawn in yawns if "yawn_start_s" in yawn]
    arrival_to_yawn = [next((round(s - arrive, 2) for s in starts if s >= arrive), None) for arrive, _ in visits]

    sheets = {}
    for jump in (graph.loop_jump, *graph.entries, *graph.exits):
        if jump.bridge is None:
            continue
        path = config.PREVIEW_DIR / f"jump_{jump.bridge}.png"
        save_png(path, jump_sheet(sequences, jump))
        sheets[jump.bridge] = repo_relative(path)

    summary = {
        "video": repo_relative(PREVIEW_VIDEO),
        "seconds": seconds,
        "seed": seed,
        "overlay": overlay,
        "visits": [[arrive, leave] for arrive, leave in visits],
        "arrival_to_yawn_s": arrival_to_yawn,
        "yawns": yawns,
        "jumps": jump_counts,
        "jump_sheets": sheets,
    }
    config.PREVIEW_JSON.write_text(json.dumps(summary, indent=2) + "\n")
    log.info("%d visits, %d yawns, arrival -> yawn: %s", len(visits), len(yawns), arrival_to_yawn)
    log.info("jumps taken: %s", jump_counts)
    log.info("wrote %s and %d jump sheets", repo_relative(PREVIEW_VIDEO), len(sheets))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=config.PREVIEW_SECONDS)
    parser.add_argument("--seed", type=int, default=config.PREVIEW_SEED)
    parser.add_argument("--no-overlay", action="store_true", help="hide the state label in the corner")
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.seconds, args.seed, overlay=not args.no_overlay)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
