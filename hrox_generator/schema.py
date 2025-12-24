"""Input schema validation and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import json

from jsonschema import Draft202012Validator

JSONDict = Dict[str, Any]

INPUT_SCHEMA: JSONDict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["project", "tracks", "clips"],
    "properties": {
        "project": {
            "type": "object",
            "required": ["name", "framerate", "samplerate", "timecodeStart"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "framerate": {"type": ["string", "number"]},
                "samplerate": {"type": ["string", "number"]},
                "timecodeStart": {"type": "integer"},
                "viewerLut": {"type": "string"},
                "ocioConfigName": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "tracks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": ["video", "audio"]},
                },
                "additionalProperties": True,
            },
            "uniqueItems": False,
        },
        "clips": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["file", "track"],
                "properties": {
                    "file": {"type": "string", "minLength": 1},
                    "track": {"type": "string", "minLength": 1},
                    "timelineIn": {"type": "integer"},
                    "timelineDuration": {"type": "integer"},
                    "sourceIn": {"type": "integer"},
                    "sourceDuration": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
    },
    "additionalProperties": False,
}


class SchemaValidationError(ValueError):
    """Raised when the user JSON fails validation."""


@dataclass
class InputProject:
    name: str
    framerate: Tuple[int, int]
    samplerate: Tuple[int, int]
    timecode_start: int
    viewer_lut: str = "ACES/Rec.709"
    ocio_config: str = "aces_1.2"

    @property
    def framerate_str(self) -> str:
        return f"{self.framerate[0]}/{self.framerate[1]}"

    @property
    def samplerate_str(self) -> str:
        return f"{self.samplerate[0]}/{self.samplerate[1]}"


@dataclass
class InputTrack:
    name: str
    kind: str = "video"


@dataclass
class InputClip:
    file_path: Path
    track: str
    timeline_in: Optional[int] = None
    timeline_duration: Optional[int] = None
    source_in: Optional[int] = None
    source_duration: Optional[int] = None
    name: Optional[str] = None


@dataclass
class InputData:
    project: InputProject
    tracks: List[InputTrack]
    clips: List[InputClip]


def load_input(source: Union[str, Path, JSONDict]) -> InputData:
    """Load and validate JSON input from path or dict."""

    if isinstance(source, (str, Path)):
        with Path(source).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    elif isinstance(source, dict):
        payload = source
    else:
        raise TypeError("load_input expects a path or dict")

    _validate_against_schema(payload)
    return _normalize(payload)


def _validate_against_schema(payload: JSONDict) -> None:
    validator = Draft202012Validator(INPUT_SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        message_lines = ["Input JSON failed validation:"]
        for err in errors:
            location = "/".join(str(part) for part in err.path)
            message_lines.append(f" - {location or '<root>'}: {err.message}")
        raise SchemaValidationError("\n".join(message_lines))


def _normalize(payload: JSONDict) -> InputData:
    project_obj = payload["project"]
    project = InputProject(
        name=project_obj["name"],
        framerate=_parse_ratio(project_obj["framerate"]),
        samplerate=_parse_ratio(project_obj["samplerate"]),
        timecode_start=int(project_obj["timecodeStart"]),
        viewer_lut=project_obj.get("viewerLut", "ACES/Rec.709"),
        ocio_config=project_obj.get("ocioConfigName", "aces_1.2"),
    )

    track_objs = [_normalize_track(obj) for obj in payload["tracks"]]
    _ensure_unique((track.name for track in track_objs), "track names must be unique")

    clips = [_normalize_clip(obj) for obj in payload["clips"]]
    known_tracks = {track.name for track in track_objs}
    dangling = {clip.track for clip in clips if clip.track not in known_tracks}
    if dangling:
        raise SchemaValidationError(
            f"Clip references unknown track(s): {', '.join(sorted(dangling))}"
        )

    return InputData(project=project, tracks=track_objs, clips=clips)


def _normalize_track(obj: JSONDict) -> InputTrack:
    return InputTrack(name=obj["name"], kind=obj.get("kind", "video"))


def _normalize_clip(obj: JSONDict) -> InputClip:
    return InputClip(
        file_path=Path(obj["file"]).expanduser(),
        track=obj["track"],
        timeline_in=_optional_int(obj.get("timelineIn")),
        timeline_duration=_optional_int(obj.get("timelineDuration")),
        source_in=_optional_int(obj.get("sourceIn")),
        source_duration=_optional_int(obj.get("sourceDuration")),
        name=obj.get("name"),
    )


def _parse_ratio(value: Union[str, int, float]) -> Tuple[int, int]:
    if isinstance(value, str):
        value = value.strip()
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return int(numerator), max(1, int(denominator))
        if value.isdigit():
            return int(value), 1
    fraction = Fraction(value).limit_denominator()
    return fraction.numerator, fraction.denominator


def _optional_int(value: Optional[Any]) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _ensure_unique(values: Iterable[str], message: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SchemaValidationError(message)
        seen.add(value)
