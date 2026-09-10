"""Run the Phase 0 analysis end to end on one source clip:
probe -> normalize -> segment -> report.

    python -m analysis.pipeline assets/raw/<clip>.mp4

Swapping in a new video is just re-running this with the new file.
"""

import argparse
import logging
import sys

from analysis import config, normalize, probe, report, segment
from analysis.cli import existing_file, setup_logging
from analysis.video_io import VideoToolError

log = logging.getLogger("pipeline")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=existing_file)
    parser.add_argument("--width", type=int, default=config.TARGET_WIDTH)
    parser.add_argument("--height", type=int, default=config.TARGET_HEIGHT)
    parser.add_argument("--fps", type=normalize.parse_frame_rate, default=None, help="default: keep the source rate")
    args = parser.parse_args()
    setup_logging()

    try:
        probe.run([args.source])
        normalized = normalize.run(args.source, args.width, args.height, args.fps)
        # A stale segments.json from an earlier clip would otherwise end up in the report.
        config.SEGMENTS_JSON.unlink(missing_ok=True)
        segment.run(normalized)
    except (ValueError, VideoToolError) as error:
        log.error("%s", error)
        report.run()
        sys.exit(1)
    report.run()


if __name__ == "__main__":
    main()
