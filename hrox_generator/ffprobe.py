"""ffprobe helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import subprocess
import uuid


@dataclass
class MediaMetadata:
    """Light-weight container for the metadata required by hieroXML."""

    path: Path
    exists: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    duration_frames: Optional[int] = None
    duration_seconds: Optional[float] = None
    frame_rate: str = "25/1"
    frame_rate_value: Optional[float] = 25.0
    samplerate: str = "0/0"
    pixel_aspect: float = 1.0
    timecode_frames: int = 0
    timecode_display: str = "00:00:00:00"
    codec_id: str = "ap4h"
    codec_name: str = "Apple ProRes 4444"
    codec_long_name: str = "Apple ProRes 4444"
    encoder: str = "Apple ProRes 4444"
    colourspace_display: str = "Output - Rec.709"
    color_matrix: str = "BT709"
    color_primaries: str = "ITU-R BT.709"
    color_transfer: str = "ITU-R BT.709"
    bits_per_channel: int = 12
    bits_per_channel_label: str = "12-bit fixed"
    channel_format: str = "integer"
    layers: str = "colour"
    has_alpha: bool = True
    layer_type_name: str = "colourAlpha"
    pixel_format_desc: str = "RGBA (Int16)  Open Color IO space: 8"
    pix_fmt: Optional[str] = None
    file_size: Optional[int] = None
    creation_time: Optional[str] = None
    modification_time: Optional[str] = None
    filereader: str = "mov64"
    quicktime_writer: str = "mov64"
    quicktime_app: str = "Nuke"
    quicktime_app_version: str = "12.0v2"
    quicktime_colorspace: str = "Output - Rec.709"
    quicktime_matrix: str = "Rec 709"
    quicktime_codec: str = "ProRes4444"
    read_colorspace: str = "Output - Rec.709"
    media_type_label: str = "QuickTime ProRes4444"
    file_type: str = "mov"
    frame_count_method: str = "static_defaults"
    file_extension: str = ""
    metadata_errors: List[str] = field(default_factory=list)
    umid: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def from_path(cls, path: Path) -> MediaMetadata:
        instance = cls(path=path, exists=path.exists())
        instance.file_extension = path.suffix.lower()
        instance.file_type = instance.file_extension.lstrip(".") or "mov"
        if instance.file_extension == ".nk":
            instance.codec_id = "nk"
            instance.codec_name = "Nuke Script"
            instance.codec_long_name = "Nuke Script"
            instance.encoder = "nk"
            instance.quicktime_codec = "nk"
            instance.media_type_label = "Nuke Script"
            instance.filereader = "nk"
            instance.quicktime_writer = "nk"
            instance.bits_per_channel = 8
            instance.bits_per_channel_label = "8-bit fixed"
            instance.has_alpha = False
            instance.layer_type_name = "colour"
            instance.pixel_format_desc = "RGBA (Int8)  Open Color IO space: 6"
        instance._apply_file_stats()
        return instance

    def _apply_file_stats(self) -> None:
        if not self.exists:
            return
        try:
            stat_result = self.path.stat()
        except OSError as exc:  # pragma: no cover - platform specific
            self.metadata_errors.append(f"stat failed: {exc}")
            return
        self.file_size = int(stat_result.st_size)
        self.creation_time = _format_timestamp(stat_result.st_ctime)
        self.modification_time = _format_timestamp(stat_result.st_mtime)

    def note_error(self, message: str) -> None:
        self.metadata_errors.append(message)


@dataclass
class FrameCountResult:
    frames: Optional[int]
    method: str
    metadata: Optional[MediaMetadata] = None
    stderr: Optional[str] = None


class FFProbeError(RuntimeError):
    """Raised when ffprobe returns an unexpected payload in strict mode."""


def get_frame_count(path: Path, ffprobe_path: Optional[str] = None, timeout: float = 10.0) -> FrameCountResult:
    """Return the frame count for ``path`` using ffprobe, with best-effort metadata."""

    metadata = probe_media_metadata(path, ffprobe_path=ffprobe_path, timeout=timeout)
    stderr = "\n".join(metadata.metadata_errors) if metadata.metadata_errors else None
    return FrameCountResult(
        frames=metadata.duration_frames,
        method=metadata.frame_count_method,
        metadata=metadata,
        stderr=stderr,
    )


def probe_media_metadata(path: Path, ffprobe_path: Optional[str] = None, timeout: float = 10.0) -> MediaMetadata:
    """Return detailed metadata for ``path`` using ffprobe with static fallbacks."""

    metadata = MediaMetadata.from_path(path)
    if not metadata.exists:
        metadata.note_error(f"File not found: {path}")
        return metadata
    if metadata.file_extension == ".nk":
        # nk scripts are not probed via ffprobe, but still return defaults
        return metadata

    executable = ffprobe_path or "ffprobe"
    cmd = _build_ffprobe_command(executable, path)
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
    except Exception as exc:  # noqa: broad-except - best effort fallback
        metadata.note_error(str(exc))
        return metadata

    try:
        payload: Dict[str, Any] = json.loads(output)
    except json.JSONDecodeError as exc:  # pragma: no cover - unexpected payloads
        metadata.note_error(f"json decode error: {exc}")
        return metadata

    _populate_metadata_from_payload(metadata, payload)
    return metadata


def _build_ffprobe_command(executable: str, path: Path) -> List[str]:
    return [
        executable,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,codec_long_name,codec_tag_string,width,height,"
            "avg_frame_rate,r_frame_rate,nb_read_frames,nb_frames,duration,bit_rate,pix_fmt,"
            "color_space,color_transfer,color_primaries,bits_per_raw_sample,sample_aspect_ratio,"
            "display_aspect_ratio,tags"
        ),
        "-show_entries",
        "format=format_name,format_long_name,duration,size,bit_rate,tags",
        "-print_format",
        "json",
        str(path),
    ]


def _populate_metadata_from_payload(metadata: MediaMetadata, payload: Dict[str, Any]) -> None:
    stream = _select_video_stream(payload.get("streams") or [])
    format_data = payload.get("format") or {}

    if stream is None:
        metadata.note_error("ffprobe returned no video streams")
        return

    metadata.width = _coerce_int(stream.get("width")) or metadata.width
    metadata.height = _coerce_int(stream.get("height")) or metadata.height
    metadata.pix_fmt = stream.get("pix_fmt") or metadata.pix_fmt
    metadata.has_alpha = _pix_fmt_has_alpha(metadata.pix_fmt)
    metadata.layer_type_name = "colourAlpha" if metadata.has_alpha else "colour"

    frame_rate_text, frame_rate_value = _parse_ratio(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if frame_rate_text:
        metadata.frame_rate = frame_rate_text
    if frame_rate_value:
        metadata.frame_rate_value = frame_rate_value

    stream_duration = _coerce_float(stream.get("duration"))
    format_duration = _coerce_float(format_data.get("duration"))
    metadata.duration_seconds = stream_duration or format_duration or metadata.duration_seconds

    frame_count = _coerce_int(stream.get("nb_read_frames")) or _coerce_int(stream.get("nb_frames"))
    if frame_count is not None:
        metadata.duration_frames = frame_count
        metadata.frame_count_method = "count_frames"
    elif metadata.duration_seconds is not None and metadata.frame_rate_value:
        metadata.duration_frames = int(round(metadata.duration_seconds * metadata.frame_rate_value))
        metadata.frame_count_method = "rate_estimate"

    metadata.codec_name = stream.get("codec_name") or metadata.codec_name
    metadata.codec_long_name = stream.get("codec_long_name") or metadata.codec_long_name
    metadata.codec_id = stream.get("codec_tag_string") or metadata.codec_id
    metadata.encoder = stream.get("codec_long_name") or metadata.encoder
    metadata.quicktime_codec = (stream.get("codec_name") or metadata.quicktime_codec)
    metadata.media_type_label = f"QuickTime {metadata.codec_name}" if metadata.file_extension == ".mov" else metadata.media_type_label

    pixel_aspect = _parse_aspect_ratio(stream.get("sample_aspect_ratio"))
    if pixel_aspect:
        metadata.pixel_aspect = pixel_aspect

    bits_per_sample = _coerce_int(stream.get("bits_per_raw_sample"))
    if bits_per_sample:
        metadata.bits_per_channel = bits_per_sample
        metadata.bits_per_channel_label = f"{bits_per_sample}-bit fixed"

    metadata.color_matrix = _normalize_colorspace(stream.get("color_space")) or metadata.color_matrix
    metadata.color_transfer = stream.get("color_transfer") or metadata.color_transfer
    metadata.color_primaries = stream.get("color_primaries") or metadata.color_primaries

    tags = stream.get("tags") or {}
    format_tags = format_data.get("tags") or {}
    metadata.timecode_display = tags.get("timecode") or format_tags.get("timecode") or metadata.timecode_display
    metadata.timecode_frames = _timecode_to_frames(metadata.timecode_display, metadata.frame_rate_value)

    metadata.creation_time = metadata.creation_time or tags.get("creation_time") or format_tags.get("creation_time")
    metadata.quicktime_colorspace = tags.get("com.apple.quicktime.colorspace") or metadata.quicktime_colorspace
    metadata.quicktime_matrix = tags.get("com.apple.quicktime.matrix") or metadata.quicktime_matrix

    format_size = _coerce_int(format_data.get("size"))
    if format_size is not None:
        metadata.file_size = format_size

    metadata.read_colorspace = metadata.colourspace_display


def _select_video_stream(streams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for stream in streams:
        if stream.get("codec_type") == "video":
            return stream
    return streams[0] if streams else None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "N/A":
            return None
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "N/A":
            return None
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _parse_ratio(text: Optional[str]) -> Tuple[str, Optional[float]]:
    if not text:
        return "", None
    try:
        fraction = Fraction(text).limit_denominator()
        value = fraction.numerator / fraction.denominator if fraction.denominator else None
        return f"{fraction.numerator}/{fraction.denominator}", value
    except (ValueError, ZeroDivisionError):
        try:
            number = float(text)
        except (TypeError, ValueError):
            return "", None
        return f"{int(number)}/1", number


def _parse_aspect_ratio(text: Optional[str]) -> Optional[float]:
    if not text or text in {"0:1", "N/A"}:
        return None
    if ":" not in text:
        return _coerce_float(text)
    left, right = text.split(":", 1)
    try:
        return float(left) / float(right)
    except (ValueError, ZeroDivisionError):
        return None


def _normalize_colorspace(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    upper = value.upper()
    if upper.startswith("BT") and not upper.startswith("BT."):
        return upper
    return value


def _timecode_to_frames(timecode: str, frame_rate: Optional[float]) -> int:
    if not timecode or frame_rate is None or frame_rate <= 0:
        return 0
    normalized = timecode.replace(";", ":")
    parts = normalized.split(":")
    if len(parts) != 4:
        return 0
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError:
        return 0
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return int(round(total_seconds * frame_rate + frames))


def _pix_fmt_has_alpha(pix_fmt: Optional[str]) -> bool:
    if not pix_fmt:
        return True
    return "a" in pix_fmt.lower()


def _format_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M:%S")
