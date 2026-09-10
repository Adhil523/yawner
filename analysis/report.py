"""Render docs/analysis-report.md from the JSON the other steps wrote.

    python -m analysis.report

Deterministic: re-running on the same inputs produces the same file.
"""

import json
import logging
from pathlib import Path
from typing import Any

from analysis import config
from analysis.cli import repo_relative, setup_logging

log = logging.getLogger("report")

_PARTS = (("head", "Still start"), ("yawn", "Yawn"), ("tail", "Still end"))


def _link(repo_path: str) -> str:
    """Link from docs/ to a repo-relative file."""
    return f"[`{Path(repo_path).name}`](../{repo_path})"


def _clip_section(probe: dict[str, Any]) -> list[str]:
    lines = [
        "## Source clip", "",
        "| Clip | Size | FPS | Frames | Duration | Codec | Audio |",
        "|---|---|---|---|---|---|---|",
    ]
    for clip in probe["clips"]:
        audio = "yes (stripped)" if clip["has_audio"] else "no"
        lines.append(
            f"| `{Path(clip['path']).name}` | {clip['width']}×{clip['height']} | {clip['frame_rate']} "
            f"| {clip['frame_count']} | {clip['duration_s']:.2f} s | {clip['codec']} / {clip['pix_fmt']} | {audio} |"
        )
    return lines


def _segment_sections(segments: dict[str, Any]) -> list[str]:
    fps = segments["fps"]
    previews = segments["previews"]
    lines = [
        "## Segments", "",
        f"Normalised clip `{segments['clip']}`: {segments['frame_count']} frames at {fps:g} fps.", "",
        "| Part | Frames | Length |",
        "|---|---|---|",
    ]
    for key, label in _PARTS:
        start, end = segments["segments"][key]
        lines.append(f"| {label} | {start}–{end} | {(end - start + 1) / fps:.2f} s |")
    lines += [
        "",
        f"Yawn = smoothed motion above {segments['threshold']:.3f} (still level {segments['still_level']:.3f}).",
    ]
    if segments["overrides"]:
        detected_start, detected_end = segments["detected_yawn"]
        lines += [
            f"Boundaries corrected by hand in `analysis/config.py` (`SEGMENT_OVERRIDES`: {segments['overrides']}); "
            f"auto-detected yawn was {detected_start}–{detected_end}.",
        ]
    lines += [
        f"Motion plot: {_link(previews['motion'])}. Frames with segment colours "
        f"(green start, red yawn, blue end): {_link(previews['contact_sheet'])}.",
        "",
        "## Natural drift in the still parts", "",
        "Mean absolute difference (grey levels, 0–255) between frames `gap` apart, on blurred "
        f"{config.DESCRIPTOR_LONG_SIDE}px-tall descriptors. This is the yardstick for seam costs.", "",
        "| Gap (frames) | Seconds | Mean change |",
        "|---|---|---|",
    ]
    for gap, value in segments["natural_drift"].items():
        lines.append(f"| {gap} | {int(gap) / fps:.2f} | {value:.3f} |")

    reference = segments["natural_drift"].get(str(config.DRIFT_REFERENCE_GAP))
    lines += [
        "",
        "## Best end → start cuts", "",
        "Windowed cost (brief 2c) of showing still-end frame *i*, then still-start frame *j*.", "",
        f"| Cut | Cost | × drift over {config.DRIFT_REFERENCE_GAP} frames |",
        "|---|---|---|",
    ]
    for cut in segments["best_end_to_start_cuts"]:
        ratio = f"{cut['cost'] / reference:.1f}×" if reference else "n/a"
        lines.append(f"| {cut['from_frame']} → {cut['to_frame']} | {cut['cost']:.3f} | {ratio} |")
    if "seam_difference" in previews:
        lines += ["", f"Best cut vs natural drift, amplified ×8: {_link(previews['seam_difference'])}."]
    return lines


def _portal_row(portal: dict[str, Any], fade: int, drift: float, with_latency: bool) -> str:
    if portal["bridge"]:
        cut = f"{portal['at'] + fade} → {portal['resume']}"
        how = f"{fade}-frame crossfade (`{portal['bridge']}`)"
        ratio = f"{portal['cost'] / drift:.1f}×"
    else:
        cut = f"{portal['at']} → {portal['resume']}"
        how = "plays straight on, no cut"
        ratio = "–"
    row = f"| {cut} | {how} | {portal['cost']:.3f} | {ratio} |"
    return row + (f" {portal['latency_s']:.2f} s |" if with_latency else "")


def _graph_sections(manifest: dict[str, Any]) -> list[str]:
    fps = manifest["fps"]
    drift = manifest["natural_drift"]
    fade = manifest["crossfade_frames"]
    loop = manifest["idle_loop"]
    length = loop["end"] - loop["start"] + 1
    lines = [
        "## Idle loop", "",
        f"Frames {loop['start']}–{loop['end']}, {length / fps:.2f} s per cycle. The last {fade} frames crossfade "
        f"into the frames just before {loop['start']}, then playback carries on at {loop['start']}.",
        f"Seam: cut {loop['end']} → {loop['start']}, cost {loop['cost']:.3f} = {loop['cost'] / drift:.1f}× "
        f"natural drift over {config.DRIFT_REFERENCE_GAP} frames.",
        "",
        "## Entries (idle → yawn)", "",
        "| Cut | How | Cost | × drift | Taking it → first yawn frame |",
        "|---|---|---|---|---|",
    ]
    lines += [_portal_row(entry, fade, drift, with_latency=True) for entry in manifest["entries"]]
    lines += [
        "",
        f"Worst case from a debounced arrival to the first yawn frame: {manifest['worst_entry_latency_s']:.2f} s "
        f"(target {config.MAX_ENTRY_LATENCY_S:g} s). The yawn then always plays to the end.",
        "",
        "## Exits (yawn → idle)", "",
        "| Cut | How | Cost | × drift |",
        "|---|---|---|---|",
    ]
    lines += [_portal_row(exit_, fade, drift, with_latency=False) for exit_ in manifest["exits"]]
    return lines


def _preview_section(preview: dict[str, Any]) -> list[str]:
    overlay = " The corner label shows the player state." if preview["overlay"] else ""
    lines = [
        "", "## Simulated run", "",
        f"{_link(preview['video'])}: {preview['seconds']:g} s, {len(preview['visits'])} scripted visits "
        f"(seed {preview['seed']}), using the debounce and behaviour settings in `player/config.toml`.{overlay}", "",
        "| Arrived | Left | Arrival → first yawn frame |",
        "|---|---|---|",
    ]
    for (arrive, leave), latency in zip(preview["visits"], preview["arrival_to_yawn_s"]):
        wait = "no yawn" if latency is None else f"{latency:.2f} s"
        lines.append(f"| {arrive:.2f} s | {leave:.2f} s | {wait} |")
    jumps = ", ".join(f"`{name}` ×{count}" for name, count in preview["jumps"].items())
    lines += [
        "",
        f"Jumps taken: {jumps}. Arrival times include the {'presence debounce'}.",
        "",
        "Close-ups of each crossfade (3 frames before, the fade, 3 frames after; below it, the hard cut it replaces):",
    ]
    lines += [f"- {_link(path)}" for path in preview["jump_sheets"].values()]
    return lines


def render(
    probe: dict[str, Any],
    segments: dict[str, Any] | None,
    manifest: dict[str, Any] | None = None,
    preview: dict[str, Any] | None = None,
) -> str:
    lines = [
        "# Analysis report", "",
        "_Generated by `python -m analysis.report` from the JSON in `build/`. "
        "Re-run the pipeline rather than editing by hand._", "",
    ]
    lines += _clip_section(probe)
    flags = probe["issues"] + (segments["issues"] if segments else []) + (manifest["flags"] if manifest else [])
    lines += ["", "## Flags", ""] + ([f"- {flag}" for flag in flags] or ["- none"])
    lines += [""]
    if segments is None:
        lines += ["_Segmentation hasn't run or failed; see the pipeline log._"]
        return "\n".join(lines) + "\n"
    lines += _segment_sections(segments)
    if manifest is not None:
        lines += [""] + _graph_sections(manifest)
    if preview is not None:
        lines += _preview_section(preview)
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def run(out: Path = config.REPORT_MD) -> Path:
    probe = _load(config.PROBE_JSON)
    if probe is None:
        raise FileNotFoundError(f"{repo_relative(config.PROBE_JSON)} missing; run analysis.probe first")
    segments = _load(config.SEGMENTS_JSON)
    manifest = _load(config.MANIFEST_JSON)
    preview = _load(config.PREVIEW_JSON)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(probe, segments, manifest, preview))
    log.info("wrote %s", repo_relative(out))
    return out


def main() -> None:
    setup_logging()
    run()


if __name__ == "__main__":
    main()
