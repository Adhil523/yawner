"""Build the frame graph and write everything the player needs (brief 2d-2h).

    python -m analysis.export build/normalized/<clip>.mkv

Needs build/segments.json from analysis.segment for the same clip. Writes
build/clips/*.mkv (the main clip plus pre-rendered crossfades, all FFV1 so any
ffmpeg decodes them exactly) and build/manifest.json, the graph the player walks.
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np

from analysis import config
from analysis.bridges import bridge_sources, crossfade
from analysis.cli import existing_file, repo_relative, setup_logging
from analysis.features import load_descriptors, pairwise_distance, windowed_distance
from analysis.find_loop import Loop, choose_loop
from analysis.find_portals import Portal, PortalPlan, decision_frame, plan_portals, portal_transition
from analysis.probe import VideoInfo, probe_video
from analysis.video_io import VideoToolError, read_frames, write_frames

log = logging.getLogger("export")

MAIN = "main"
LOOP_BRIDGE = "bridge_loop"
MANIFEST_VERSION = 1


def load_segments(clip: Path) -> dict[str, Any]:
    if not config.SEGMENTS_JSON.is_file():
        raise ValueError(f"{repo_relative(config.SEGMENTS_JSON)} missing; run analysis.segment first")
    segments = json.loads(config.SEGMENTS_JSON.read_text())
    if segments["clip"] != repo_relative(clip):
        raise ValueError(
            f"{repo_relative(config.SEGMENTS_JSON)} describes {segments['clip']}, not {repo_relative(clip)}; "
            "re-run analysis.segment"
        )
    return segments


def build_graph(windowed: np.ndarray, segments: dict[str, Any], fps: float) -> tuple[Loop, PortalPlan]:
    parts = segments["segments"]
    head, yawn, tail = ((int(parts[key][0]), int(parts[key][1])) for key in ("head", "yawn", "tail"))
    drift = segments["natural_drift"][str(config.DRIFT_REFERENCE_GAP)]
    loop = choose_loop(
        windowed, [head, tail], config.CROSSFADE_FRAMES, config.MIN_LOOP_FRAMES, config.INVISIBLE_SEAM_RATIO * drift
    )
    max_latency = round(config.MAX_ENTRY_LATENCY_S * fps)
    return loop, plan_portals(windowed, loop, head, yawn, tail, config.CROSSFADE_FRAMES, max_latency)


def find_flags(loop: Loop, plan: PortalPlan, drift: float, fps: float) -> list[str]:
    flags: list[str] = []
    if loop.cost > config.INVISIBLE_SEAM_RATIO * drift:
        flags.append(f"idle loop seam costs {loop.cost / drift:.1f}x natural drift; it may be visible")
    for kind, portals in (("entry", plan.entries), ("exit", plan.exits)):
        for portal in portals:
            if portal.bridged and portal.cost > config.CUT_DRIFT_RATIO_FLAG * drift:
                flags.append(
                    f"{kind} cut {portal.at + config.CROSSFADE_FRAMES} -> {portal.resume} costs "
                    f"{portal.cost / drift:.1f}x natural drift; review its jump sheet"
                )
    worst = plan.worst_entry_latency / fps
    if worst > config.MAX_ENTRY_LATENCY_S:
        flags.append(f"worst arrival-to-yawn wait is {worst:.2f} s, over the {config.MAX_ENTRY_LATENCY_S:g} s target")
    return flags


def write_clips(clip: Path, info: VideoInfo, bridges: dict[str, tuple[int, int]]) -> None:
    """Copy the main clip and render one crossfade per bridge (name -> (at, resume))."""
    config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in config.CLIPS_DIR.glob("*.mkv"):
        stale.unlink()
    shutil.copyfile(clip, config.CLIPS_DIR / f"{MAIN}.mkv")

    sources = {name: bridge_sources(at, resume, config.CROSSFADE_FRAMES) for name, (at, resume) in bridges.items()}
    wanted = sorted({index for outgoing, incoming in sources.values() for index in (*outgoing, *incoming)})
    frames = dict(zip(wanted, read_frames(clip, info.width, info.height, indices=wanted)))
    for name, (outgoing, incoming) in sources.items():
        blended = crossfade(np.stack([frames[i] for i in outgoing]), np.stack([frames[i] for i in incoming]))
        write_frames(config.CLIPS_DIR / f"{name}.mkv", blended, info.frame_rate)


def _portal_json(portal: Portal, bridge: str | None, fps: float, entry: bool) -> dict[str, Any]:
    data: dict[str, Any] = {"at": portal.at, "resume": portal.resume, "bridge": bridge, "cost": round(portal.cost, 4)}
    if entry:
        data["latency_s"] = round(portal_transition(portal, config.CROSSFADE_FRAMES) / fps, 3)
    return data


def run(clip: Path, manifest_out: Path = config.MANIFEST_JSON) -> dict[str, Any]:
    segments = load_segments(clip)
    info = probe_video(clip)
    descriptors = load_descriptors(clip)
    windowed = windowed_distance(pairwise_distance(descriptors, descriptors))
    loop, plan = build_graph(windowed, segments, info.fps)
    drift = segments["natural_drift"][str(config.DRIFT_REFERENCE_GAP)]
    fade = config.CROSSFADE_FRAMES

    entry_names = [f"bridge_entry_{i}" if p.bridged else None for i, p in enumerate(plan.entries)]
    exit_names = [f"bridge_exit_{i}" if p.bridged else None for i, p in enumerate(plan.exits)]
    loop_decision = decision_frame(loop, fade)
    bridges = {LOOP_BRIDGE: (loop_decision, loop.start)}
    for names, portals in ((entry_names, plan.entries), (exit_names, plan.exits)):
        bridges |= {name: (p.at, p.resume) for name, p in zip(names, portals) if name}
    write_clips(clip, info, bridges)

    sequences = {MAIN: {"file": f"clips/{MAIN}.mkv", "frames": len(descriptors)}}
    sequences |= {name: {"file": f"clips/{name}.mkv", "frames": fade} for name in bridges}
    flags = find_flags(loop, plan, drift, info.fps)
    manifest = {
        "version": MANIFEST_VERSION,
        "clip": repo_relative(clip),
        "frame_rate": info.frame_rate,
        "fps": info.fps,
        "resolution": [info.width, info.height],
        "crossfade_frames": fade,
        "natural_drift": drift,
        "sequences": sequences,
        "idle_loop": {
            "start": loop.start,
            "end": loop.end,
            "cost": round(loop.cost, 4),
            "jump": {"at": loop_decision, "bridge": LOOP_BRIDGE, "resume": loop.start},
        },
        "yawn": {"start": segments["segments"]["yawn"][0], "end": segments["segments"]["yawn"][1]},
        "entries": [_portal_json(p, n, info.fps, entry=True) for p, n in zip(plan.entries, entry_names)],
        "exits": [_portal_json(p, n, info.fps, entry=False) for p, n in zip(plan.exits, exit_names)],
        "worst_entry_latency_s": round(plan.worst_entry_latency / info.fps, 3),
        "flags": flags,
    }
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2) + "\n")

    log.info("idle loop %d-%d (%.2f s), seam cost %.3f", loop.start, loop.end, loop.length / info.fps, loop.cost)
    for portal in plan.entries:
        log.info("entry after frame %d -> %d, cost %.3f", portal.at, portal.resume, portal.cost)
    for portal in plan.exits:
        log.info("exit after frame %d -> %d, cost %.3f", portal.at, portal.resume, portal.cost)
    log.info("worst arrival-to-yawn wait %.2f s", plan.worst_entry_latency / info.fps)
    for flag in flags:
        log.info("flag: %s", flag)
    log.info("wrote %s and %d clips in %s", repo_relative(manifest_out), len(sequences), repo_relative(config.CLIPS_DIR))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", type=existing_file, help="normalised clip, e.g. build/normalized/<clip>.mkv")
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.clip)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
