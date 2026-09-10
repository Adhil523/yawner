"""Helpers shared by the analysis command-line entry points."""

import argparse
import logging
from pathlib import Path

from analysis import config


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")


def existing_file(value: str) -> Path:
    """argparse type: reject paths that don't point at a file."""
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"not a file: {value}")
    return path


def repo_relative(path: Path) -> str:
    """Path relative to the repo root when inside it, so reports don't leak home paths."""
    resolved = path.resolve()
    if resolved.is_relative_to(config.REPO_ROOT):
        return str(resolved.relative_to(config.REPO_ROOT))
    return str(resolved)
