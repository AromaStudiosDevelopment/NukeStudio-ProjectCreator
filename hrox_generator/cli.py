"""Command line interface for hrox-generator."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

from .generator import GenerationOptions, generate_hrox
from .schema import load_input

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Hiero/Nuke Studio .hrox files from JSON input")
    parser.add_argument("--input", required=True, help="Path to the input JSON schema file")
    parser.add_argument("--output", required=True, help="Path to write the resulting .hrox file")
    parser.add_argument("--ffprobe-path", dest="ffprobe_path", help="Custom ffprobe executable path")
    parser.add_argument("--path-base", dest="path_base", help="Optional base path to strip from media paths")
    parser.add_argument("--use-relative-paths", action="store_true", help="Emit media paths relative to the output file")
    parser.add_argument("--project-directory", default="", help="Value for Project.project_directory")
    parser.add_argument("--target-release", default="12.2v2", help="Release string stored on <hieroXML>")
    parser.add_argument("--target-version", default="11", help="Version string stored on <hieroXML>")
    parser.add_argument("--strict", action="store_true", help="Fail if any media file is missing")
    parser.add_argument("--dry-run", action="store_true", help="Build XML but skip writing the .hrox file")
    parser.add_argument("--report", help="Optional JSON report output path")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="[%(levelname)s] %(message)s")

    input_data = load_input(Path(args.input))
    options = GenerationOptions(
        ffprobe_path=args.ffprobe_path,
        strict_paths=args.strict,
        use_relative_paths=args.use_relative_paths,
        path_base=Path(args.path_base).resolve() if args.path_base else None,
        project_directory=args.project_directory,
        target_release=args.target_release,
        target_version=args.target_version,
        dry_run=args.dry_run,
        report_path=Path(args.report) if args.report else None,
    )
    generate_hrox(input_data, Path(args.output), options=options)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
