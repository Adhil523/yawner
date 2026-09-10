"""Shared paths and analysis defaults. Every tunable lives here."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "assets" / "raw"
VIDEO_PREVIEW_DIR = REPO_ROOT / "assets" / "preview"
BUILD_DIR = REPO_ROOT / "build"
NORMALIZED_DIR = BUILD_DIR / "normalized"
PREVIEW_DIR = BUILD_DIR / "preview"
CLIPS_DIR = BUILD_DIR / "clips"
PROBE_JSON = BUILD_DIR / "probe.json"
SEGMENTS_JSON = BUILD_DIR / "segments.json"
MANIFEST_JSON = BUILD_DIR / "manifest.json"
PREVIEW_JSON = PREVIEW_DIR / "preview.json"
REPORT_MD = REPO_ROOT / "docs" / "analysis-report.md"

# Normalisation target. Portrait, because the source clip is 1080x1920.
TARGET_WIDTH = 720
TARGET_HEIGHT = 1280
MAX_ASPECT_MISMATCH = 0.01

# Frame descriptors (brief 2b): small, grayscale, lightly blurred.
DESCRIPTOR_LONG_SIDE = 160
DESCRIPTOR_BLUR_SIGMA = 1.0

# Windowed distance (brief 2c): binomial weights, m = 2.
WINDOW_WEIGHTS = (1.0, 4.0, 6.0, 4.0, 1.0)

# Segmentation. The clip must start and end with the man standing still.
EDGE_FRACTION = 0.1  # share of frames at each end used to estimate the still level
ENERGY_SMOOTH_WINDOW = 7  # median filter width; removes 1-3 frame glitches
ONSET_FRACTION = 0.1  # yawn threshold = still + fraction * (peak - still)

# Human corrections to the detected yawn boundaries, keyed by source clip stem.
# Set after reviewing build/preview/contact_sheet.png; any other clip is auto-detected only.
SEGMENT_OVERRIDES: dict[str, dict[str, int]] = {
    # 2026-09-10: frames 21-35 look neutral in the contact sheet; detection put the onset at 21.
    "Man_yawning_on_white_background_202609071453": {"onset": 36},
    # 2026-09-10: ignore the opening settling movement; the natural yawn begins around frame 152.
    "man_yawn_natural_neutral": {"onset": 152, "offset": 309},
}

# Sanity checks.
MIN_CLIP_SECONDS = 3.0
MIN_IDLE_SECONDS = 3.0
LOW_BITS_PER_PIXEL = 0.05

# Seam calibration: how much the picture drifts on its own over N frames.
DRIFT_GAPS = (1, 2, 4, 8, 12, 16, 24)
DRIFT_REFERENCE_GAP = 8  # roughly a crossfade length
CUT_DRIFT_RATIO_FLAG = 2.0
TOP_CUTS = 5

# Frame graph (brief 2d-2g).
CROSSFADE_FRAMES = 8
MIN_LOOP_FRAMES = 12  # shortest idle loop worth considering (0.5 s at 24 fps)
INVISIBLE_SEAM_RATIO = 1.0  # a seam costing <= this x natural drift counts as invisible
MAX_ENTRY_LATENCY_S = 1.5  # brief section 6: worst arrival-to-yawn wait to aim for

# Simulated-arrival preview (brief 2i).
PREVIEW_SECONDS = 75.0
PREVIEW_SEED = 7
