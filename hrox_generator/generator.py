"""Core hieroXML generation logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import os
import uuid
import re

try:  # pragma: no cover - exercised indirectly
    from lxml import etree as ET  # type: ignore

    HAVE_LXML = True
except ImportError:  # pragma: no cover - fallback path
    import xml.etree.ElementTree as ET  # type: ignore

    HAVE_LXML = False

from .ffprobe import FrameCountResult, MediaMetadata, get_frame_count
from .schema import InputClip, InputData

LOGGER = logging.getLogger(__name__)


@dataclass
class GenerationOptions:
    ffprobe_path: Optional[str] = None
    strict_paths: bool = False
    use_relative_paths: bool = False
    path_base: Optional[Path] = None
    project_directory: str = ""
    target_release: str = "12.2v2"
    target_version: str = "11"
    dry_run: bool = False
    report_path: Optional[Path] = None
    output_path: Optional[Path] = None


@dataclass
class GenerationReport:
    warnings: List[str] = field(default_factory=list)
    sources: List[Dict[str, object]] = field(default_factory=list)
    clips: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "warnings": self.warnings,
            "sources": self.sources,
            "clips": self.clips,
        }


@dataclass
class SourceRecord:
    path: Path
    display_path: str
    guid: str
    name: str
    exists: bool
    duration: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    metadata: Optional[MediaMetadata] = None


@dataclass
class TrackItemRecord:
    guid: str  # Timeline track-item guid (type=0)
    source_track_item_guid: str
    clip_guid: str
    clip: InputClip
    source: SourceRecord
    timeline_in: int
    timeline_duration: int
    source_in: int
    source_duration: int
    context: NamingContext
    clip_name: str
    timeline_link_group_guid: str
    source_link_group_guid: str


NAME_PATTERN = re.compile(
    r"(?P<project>[A-Za-z0-9]+)_(?P<episode>ep\d+)_(?P<scene>sc\d+_[^_/]+)_(?P<shot>sh\d+)_(?P<plate>pl\d+)_(?P<version>v\d+)",
    re.IGNORECASE,
)


@dataclass
class NamingContext:
    project: str
    episode: str
    scene: str
    shot: str
    plate: str
    version: str



def generate_hrox(input_data: InputData, out_path: Path | str, options: Optional[GenerationOptions] = None) -> GenerationReport:
    """Generate a .hrox file from ``input_data`` and return a report."""

    opts = options or GenerationOptions()
    output_path = Path(out_path)
    opts.output_path = output_path
    builder = _HieroBuilder(input_data=input_data, options=opts)
    root = builder.build()

    if not opts.dry_run:
        _write_tree(root, output_path)
        LOGGER.info("Wrote hieroXML to %s", output_path)
    else:
        LOGGER.info("Dry run enabled – not writing %s", output_path)

    report = builder.report
    if opts.report_path:
        Path(opts.report_path).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        LOGGER.info("Report written to %s", opts.report_path)
    return report


class _HieroBuilder:
    def __init__(self, input_data: InputData, options: GenerationOptions) -> None:
        self.input = input_data
        self.options = options
        self.report = GenerationReport()
        self.sources: Dict[str, SourceRecord] = {}
        self.track_items: List[TrackItemRecord] = []
        self.track_state: Dict[str, Dict[str, object]] = {
            track.name: {"cursor": 0, "guid": _braced_uuid(), "items": []}
            for track in input_data.tracks
        }
        self.naming = self._infer_naming_context()
        self.primary_track = self._resolve_primary_track()
        self.master_sequence_guid: Optional[str] = None
        self.master_sequence_version_guid: Optional[str] = None
        self.master_sequence_root_guid: Optional[str] = None

    def build(self):  # noqa: D401 - returns XML root element
        self._collect_sources_and_track_items()
        return self._build_xml()

    def _collect_sources_and_track_items(self) -> None:
        for clip in self.input.clips:
            context = self._infer_clip_context(clip)
            source = self._get_or_create_source(clip)
            duration = self._ensure_duration(clip, source)
            cursor = self._current_cursor(clip.track)
            timeline_in = cursor
            if clip.timeline_in is not None:
                timeline_in = max(cursor, clip.timeline_in)
            timeline_duration = clip.timeline_duration or duration or 0
            source_in = clip.source_in or 0
            source_duration = clip.source_duration or duration or timeline_duration
            clip_name = clip.name or clip.file_path.stem

            record = TrackItemRecord(
                guid=_braced_uuid(),
                source_track_item_guid=_braced_uuid(),
                clip_guid=_braced_uuid(),
                clip=clip,
                source=source,
                timeline_in=timeline_in,
                timeline_duration=timeline_duration,
                source_in=source_in,
                source_duration=source_duration or 0,
                context=context,
                clip_name=clip_name,
                timeline_link_group_guid=_braced_uuid(),
                source_link_group_guid=_braced_uuid(),
            )
            self.track_items.append(record)
            self.track_state[clip.track]["items"].append(record)
            if clip.timeline_in is None:
                self.track_state[clip.track]["cursor"] = timeline_in + timeline_duration
            else:
                self.track_state[clip.track]["cursor"] = max(
                    self.track_state[clip.track]["cursor"], timeline_in + timeline_duration
                )

            self.report.clips.append(
                {
                    "name": clip.name or clip.file_path.stem,
                    "track": clip.track,
                    "timeline_in": timeline_in,
                    "timeline_duration": timeline_duration,
                    "source_guid": source.guid,
                    "clip_guid": record.clip_guid,
                }
            )

    def _infer_naming_context(self) -> NamingContext:
        default = NamingContext(
            project=self.input.project.name,
            episode="ep000",
            scene="sc000_default",
            shot="sh0000",
            plate="pl01",
            version="v01",
        )
        for clip in self.input.clips:
            candidates = [clip.file_path.stem, clip.file_path.name, str(clip.file_path).replace("\\", "/")]
            for text in candidates:
                match = NAME_PATTERN.search(text)
                if match:
                    data = {key: match.group(key) for key in match.groupdict()}
                    return NamingContext(
                        project=data["project"],
                        episode=data["episode"],
                        scene=data["scene"],
                        shot=data["shot"],
                        plate=data["plate"],
                        version=data["version"],
                    )
        return default

    def _infer_clip_context(self, clip: InputClip) -> NamingContext:
        base = self.naming
        candidates = [
            clip.name,
            clip.file_path.stem,
            clip.file_path.name,
            str(clip.file_path).replace("\\", "/"),
        ]
        for text in candidates:
            if not text:
                continue
            match = NAME_PATTERN.search(text)
            if match:
                data = {key: match.group(key) for key in match.groupdict()}
                return NamingContext(
                    project=data["project"],
                    episode=data["episode"],
                    scene=data["scene"],
                    shot=data["shot"],
                    plate=data["plate"],
                    version=data["version"],
                )
        return base

    def _resolve_primary_track(self) -> str:
        video_tracks = [track.name for track in self.input.tracks if track.kind == "video"]
        if self.naming.plate in video_tracks:
            return self.naming.plate
        if video_tracks:
            return video_tracks[0]
        return self.input.tracks[0].name

    def _get_or_create_source(self, clip: InputClip) -> SourceRecord:
        exists = clip.file_path.exists()
        key = str(clip.file_path.resolve() if exists else clip.file_path)
        if key in self.sources:
            return self.sources[key]

        if not exists:
            message = f"File not found: {clip.file_path}"
            if self.options.strict_paths:
                raise FileNotFoundError(message)
            LOGGER.warning(message)
            self.report.warnings.append(message)

        display_path = _format_path(clip.file_path, self.options)
        if not exists:
            display_path = f"MISSING:{display_path}"

        record = SourceRecord(
            path=clip.file_path,
            display_path=display_path,
            guid=_braced_uuid(),
            name=clip.name or clip.file_path.stem,
            exists=exists,
            metadata=MediaMetadata.from_path(clip.file_path),
        )
        self.sources[key] = record
        self.report.sources.append(
            {
                "guid": record.guid,
                "path": display_path,
                "exists": exists,
            }
        )
        return record

    def _ensure_duration(self, clip: InputClip, source: SourceRecord) -> Optional[int]:
        if clip.source_duration is not None:
            source.duration = clip.source_duration
            if source.metadata is None:
                source.metadata = MediaMetadata.from_path(source.path)
            source.metadata.duration_frames = clip.source_duration
            source.metadata.frame_count_method = "schema"
            return clip.source_duration
        if source.duration is not None:
            return source.duration

        if not source.exists:
            warning = f"Duration unavailable for missing file {source.display_path}"
            self.report.warnings.append(warning)
            LOGGER.warning(warning)
            return None

        result: FrameCountResult = get_frame_count(source.path, ffprobe_path=self.options.ffprobe_path)
        if result.metadata is not None:
            source.metadata = result.metadata
        source.duration = result.frames
        if source.metadata and source.metadata.metadata_errors:
            for meta_warning in source.metadata.metadata_errors:
                warning = f"Metadata warning for {source.path}: {meta_warning}"
                self.report.warnings.append(warning)
                LOGGER.warning(warning)
        if result.frames is None:
            warning = f"ffprobe could not determine duration for {source.path}"
            self.report.warnings.append(warning)
            LOGGER.warning(warning)
        elif result.method != "count_frames":
            warning = f"Duration for {source.path} estimated via {result.method}"
            self.report.warnings.append(warning)
            LOGGER.info(warning)
        return source.duration

    def _current_cursor(self, track_name: str) -> int:
        return int(self.track_state[track_name]["cursor"])

    def _build_xml(self):
        root_attrs = {
            "name": "NukeStudio",
            "version": self.options.target_version,
            "revision": "0",
            "release": self.options.target_release,
        }
        root = ET.Element("hieroXML", root_attrs)
        self._build_media_section(root)
        self._build_project_section(root)
        self._build_ui_state(root)
        self._build_track_item_link_groups(root)
        self._build_track_item_collection(root)
        return root

    def _build_track_item_link_groups(self, root) -> None:
        groups_el = ET.SubElement(root, "TrackItemLinkGroups")
        for record in self.track_items:
            self._append_link_group(groups_el, record.timeline_link_group_guid, record.guid)
            self._append_link_group(groups_el, record.source_link_group_guid, record.source_track_item_guid)

    def _append_link_group(self, groups_el, guid: str, track_item_guid: str) -> None:
        group_el = ET.SubElement(groups_el, "TrackItemLinkGroup", {"guid": guid, "objName": "links"})
        items_el = ET.SubElement(group_el, "trackItems")
        ET.SubElement(items_el, "TrackItem", {"guid": track_item_guid, "link": "internal"})

    def _build_media_section(self, root) -> None:
        media_el = ET.SubElement(root, "Media")
        for record in self.sources.values():
            if record.metadata is None:
                record.metadata = MediaMetadata.from_path(record.path)
            attrs = {
                "file": record.display_path,
                "objName": "media",
                "name": record.name,
                "guid": record.guid,
            }
            if record.duration is not None:
                attrs["duration"] = str(record.duration)
            source_el = ET.SubElement(media_el, "Source", attrs)
            self._build_media_sets(source_el, record)
            self._build_media_times(source_el, record)
            self._build_media_layers(source_el, record)
        self._build_clip_entries(media_el)

    def _build_media_sets(self, source_el, record: SourceRecord) -> None:
        meta = record.metadata or MediaMetadata.from_path(record.path)
        sets_el = ET.SubElement(source_el, "sets")
        duration_value = record.duration if record.duration is not None else meta.duration_frames or 0
        path_text = record.path.as_posix()
        self._create_value_set(
            sets_el,
            "Media",
            "foundry.source",
            [
                ("WeakObjRefValue", "foundry.source.umid", meta.umid, "1"),
                ("StringValue", "foundry.source.umidOriginator", "foundry.source.umid", "1"),
                ("IntegerValue", "foundry.source.width", meta.width or 0, "1"),
                ("IntegerValue", "foundry.source.height", meta.height or 0, "1"),
                ("IntegerValue", "foundry.source.duration", duration_value, "1"),
                ("TimeBaseValue", "foundry.source.framerate", meta.frame_rate, "1"),
                ("TimeBaseValue", "foundry.source.samplerate", meta.samplerate, "1"),
                ("IntegerValue", "foundry.source.starttime", 0, "1"),
                ("IntegerValue", "foundry.source.timecode", meta.timecode_frames, "1"),
                ("BooleanValue", "foundry.source.timecodedropframe", "No", "1"),
                ("IntegerValue", "foundry.source.bitsperchannel", meta.bits_per_channel, "1"),
                ("IntegerValue", "foundry.source.fragments", 1, "1"),
                ("StringValue", "foundry.source.path", path_text, "1"),
                ("StringValue", "foundry.source.shortfilename", record.path.name, "1"),
                ("StringValue", "foundry.source.filename", record.path.name, "1"),
                ("FloatValue", "foundry.source.pixelAspect", meta.pixel_aspect, "1"),
                ("IntegerValue", "foundry.source.shoottime", 4294967295, "1"),
                ("StringValue", "foundry.source.reelID", "", "1"),
                ("StringValue", "foundry.source.type", meta.media_type_label, "1"),
                ("StringValue", "foundry.source.channelformat", meta.channel_format, "1"),
                ("StringValue", "foundry.source.layers", meta.layers, "1"),
                ("IntegerValue", "foundry.source.bitmapsize", meta.file_size or 0, "1"),
                ("StringValue", "foundry.source.pixelformat", meta.pixel_format_desc, "1"),
            ],
        )
        self._create_value_set(
            sets_el,
            "media.input",
            "media.input",
            [
                ("StringValue", "media.input.bitsperchannel", meta.bits_per_channel_label, "1"),
                ("StringValue", "media.input.ctime", meta.creation_time, "1"),
                ("StringValue", "media.input.filename", path_text, "1"),
                ("StringValue", "media.input.filereader", meta.filereader, "1"),
                ("IntegerValue", "media.input.filesize", meta.file_size or 0, "1"),
                ("IntegerValue", "media.input.frame", 1, "1"),
                ("FloatValue", "media.input.frame_rate", meta.frame_rate_value, "1"),
                ("IntegerValue", "media.input.height", meta.height or 0, "1"),
                ("StringValue", "media.input.mtime", meta.modification_time, "1"),
                ("FloatValue", "media.input.pixel_aspect", meta.pixel_aspect, "1"),
                ("StringValue", "media.input.timecode", meta.timecode_display, "1"),
                ("IntegerValue", "media.input.width", meta.width or 0, "1"),
            ],
        )
        if meta.file_extension in {".mov", ".mp4", ".m4v"}:
            self._create_value_set(
                sets_el,
                "media.quicktime",
                "media.quicktime",
                [
                    ("StringValue", "media.quicktime.codec_id", meta.codec_id, "1"),
                    ("StringValue", "media.quicktime.codec_name", meta.codec_name, "1"),
                    ("StringValue", "media.quicktime.encoder", meta.encoder, "1"),
                    ("StringValue", "media.quicktime.nclc_matrix", meta.color_matrix, "1"),
                    ("StringValue", "media.quicktime.nclc_primaries", meta.color_primaries, "1"),
                    (
                        "StringValue",
                        "media.quicktime.nclc_transfer_function",
                        meta.color_transfer,
                        "1",
                    ),
                ],
            )
            qt_defaults = [
                ("StringValue", "media.quicktime.thefoundry.Application", meta.quicktime_app, "1"),
                (
                    "StringValue",
                    "media.quicktime.thefoundry.ApplicationVersion",
                    meta.quicktime_app_version,
                    "1",
                ),
                (
                    "StringValue",
                    "media.quicktime.thefoundry.Colorspace",
                    meta.quicktime_colorspace,
                    "1",
                ),
                ("StringValue", "media.quicktime.thefoundry.Writer", meta.quicktime_writer, "1"),
                ("StringValue", "media.quicktime.thefoundry.YCbCrMatrix", meta.quicktime_matrix, "1"),
            ]
            self._create_value_set(sets_el, "media.quicktime.thefoundry", "media.quicktime.thefoundry", qt_defaults)
            self._create_value_set(
                sets_el,
                "uk.co.thefoundry",
                "uk.co.thefoundry",
                [
                    ("StringValue", "uk.co.thefoundry.Application", meta.quicktime_app, "1"),
                    (
                        "StringValue",
                        "uk.co.thefoundry.ApplicationVersion",
                        meta.quicktime_app_version,
                        "1",
                    ),
                    ("StringValue", "uk.co.thefoundry.Colorspace", meta.quicktime_colorspace, "1"),
                    ("StringValue", "uk.co.thefoundry.Writer", meta.quicktime_writer, "1"),
                    ("StringValue", "uk.co.thefoundry.YCbCrMatrix", meta.quicktime_matrix, "1"),
                ],
            )
            self._create_value_set(
                sets_el,
                "QuickTime",
                "com.apple.quicktime",
                [("StringValue", "com.apple.quicktime.codec", meta.quicktime_codec, "1")],
            )

    def _build_media_times(self, source_el, record: SourceRecord) -> None:
        meta = record.metadata or MediaMetadata.from_path(record.path)
        basen, based = _split_ratio(meta.frame_rate)
        duration_value = record.duration if record.duration is not None else meta.duration_frames or 0
        times_el = ET.SubElement(source_el, "times")
        map_item = ET.SubElement(times_el, "MediaDesc_TimeInfo_MapItem")
        media_desc = ET.SubElement(
            map_item,
            "MediaDesc",
            {"objName": "k", "channelIndex": "0", "streamIndex": "-1", "outputChannel": "-2"},
        )
        ET.SubElement(media_desc, "MediaFlags", {"objName": "flags", "allone": "1"})
        ET.SubElement(media_desc, "MediaType", {"type": "0", "objName": "type"})
        ET.SubElement(
            map_item,
            "TimeInfo",
            {
                "objName": "v",
                "basen": str(basen),
                "based": str(based),
                "duration": str(duration_value),
                "in": "0",
            },
        )

    def _build_media_layers(self, source_el, record: SourceRecord) -> None:
        meta = record.metadata or MediaMetadata.from_path(record.path)
        layers_el = ET.SubElement(source_el, "Layers")
        layer_attrs = {
            "layerName": meta.layers,
            "layerTypeName": meta.layer_type_name,
            "ch0": "r",
            "ch1": "g",
            "ch2": "b",
            "ch3": "a" if meta.has_alpha else "",
        }
        ET.SubElement(layers_el, "Layer", layer_attrs)

    def _build_clip_entries(self, media_el) -> None:
        for record in self.track_items:
            self._build_single_clip(media_el, record)

    def _build_single_clip(self, media_el, record: TrackItemRecord) -> None:
        meta = record.source.metadata or MediaMetadata.from_path(record.source.path)
        attrs = {
            "name": record.clip_name,
            "guid": record.clip_guid,
            "timeOffset": "0",
            "timecodeStart": str(meta.timecode_frames or 0),
            "objName": "media",
            "displayDropFrames": "0",
            "displayTimecode": "1",
            "useSoftTrims": "0",
            "timeDisplayFormat": "0",
        }
        clip_el = ET.SubElement(media_el, "Clip", attrs)
        self._build_clip_tracks(clip_el, record)
        self._build_clip_sets(clip_el, record, meta)
        self._build_clip_node(clip_el, record, meta)

    def _build_clip_tracks(self, clip_el, record: TrackItemRecord) -> None:
        videotracks_el = ET.SubElement(clip_el, "videotracks")
        video_track_el = ET.SubElement(
            videotracks_el,
            "VideoTrack",
            {
                "name": "Video 1",
                "guid": _braced_uuid(),
                "height": "40",
                "collapsed": "0",
            },
        )
        track_items_el = ET.SubElement(video_track_el, "trackItems")
        ET.SubElement(track_items_el, "TrackItem", {"link": "internal", "guid": record.source_track_item_guid})
        self._add_track_enabled_set(video_track_el)

    def _build_clip_sets(self, clip_el, record: TrackItemRecord, meta: MediaMetadata) -> None:
        project = self.input.project
        sets_el = ET.SubElement(clip_el, "sets")
        timeline_set = ET.SubElement(sets_el, "Set", {"title": "Timeline", "domainroot": "foundry.timeline"})
        values_el = ET.SubElement(timeline_set, "values")
        ET.SubElement(
            values_el,
            "TimeBaseValue",
            {"name": "foundry.timeline.framerate", "value": project.framerate_str, "default": "1"},
        )
        ET.SubElement(
            values_el,
            "TimeBaseValue",
            {"name": "foundry.timeline.samplerate", "value": project.samplerate_str, "default": "1"},
        )
        ET.SubElement(
            values_el,
            "IntegerValue",
            {"name": "foundry.timeline.duration", "value": str(record.timeline_duration), "default": "0"},
        )
        ET.SubElement(
            values_el,
            "IntegerValue",
            {"name": "foundry.timeline.poster", "value": "0", "default": "1"},
        )
        ET.SubElement(
            values_el,
            "StringValue",
            {"name": "foundry.timeline.posterLayer", "value": "colour", "default": "1"},
        )
        width = meta.width or 2048
        height = meta.height or 1152
        ET.SubElement(
            values_el,
            "MediaFormatValue",
            {
                "name": "foundry.timeline.outputformat",
                "value": f"1,[ 0, 0, {width}, {height}],[ 0, 0, {width}, {height}],Custom Format",
                "default": "1",
            },
        )
        media_set = ET.SubElement(sets_el, "Set", {"title": "Media", "domainroot": "foundry.source"})
        media_values = ET.SubElement(media_set, "values")
        ET.SubElement(
            media_values,
            "StringValue",
            {"name": "foundry.source.reelID", "value": "", "default": "1"},
        )

    def _build_clip_node(self, clip_el, record: TrackItemRecord, meta: MediaMetadata) -> None:
        width = meta.width or 2048
        height = meta.height or 1152
        duration = record.timeline_duration or record.source_duration or 0
        format_string = f"{width} {height} 0 0 {width} {height} 1 "
        extension = meta.file_extension.lstrip(".") if meta.file_extension else record.source.path.suffix.lstrip(".")
        node_lines = [
            "Read {",
            " inputs 0",
            f" file_type {extension or 'mov'}",
            f" file {record.source.path.as_posix()}",
            f" format \"{format_string}\"",
            f" last {duration}",
            f" origlast {duration}",
            " origset true",
            f" name {record.clip_name}_1",
            "}",
        ]
        node_el = ET.SubElement(clip_el, "node")
        node_el.text = "\n".join(node_lines)

    def _create_value_set(self, parent, title: str, domain: str, values: List[Tuple[str, str, Any, str]]) -> None:
        filtered = [(tag, name, value, default) for tag, name, value, default in values if value is not None]
        if not filtered:
            return
        set_el = ET.SubElement(parent, "Set", {"title": title, "domainroot": domain})
        values_el = ET.SubElement(set_el, "values")
        for tag, name, value, default in filtered:
            ET.SubElement(values_el, tag, {"name": name, "value": _format_value(value), "default": default})

    def _build_project_section(self, root) -> None:
        project = self.input.project
        naming = self.naming
        attrs = {
            "project_directory": self.options.project_directory,
            "samplerate": project.samplerate_str,
            "framerate": project.framerate_str,
            "name": naming.project,
            "guid": _braced_uuid(),
            "starttimecode": str(project.timecode_start),
            "viewerLut": project.viewer_lut,
            "ocioConfigName": project.ocio_config,
            "nukeUseOCIO": "1",
            "timelineReformatType": "Disabled",
            "timelineReformatCenter": "1",
            "timelineReformatResizeType": "Width",
            "timedisplayformat": "0",
            "HeroView": "0",
            "shotPresetName": "Basic Nuke Shot With Annotations",
            "buildTrackName": "VFX",
            "exportRootPathMode": "ProjectDirectory",
            "ocioConfigCustom": "0",
            "posterFrameSetting": "First",
            "posterCustomFrame": "0",
            "useViewColors": "0",
            "logLut": "compositing_log",
            "floatLut": "scene_linear",
            "sixteenBitLut": "texture_paint",
            "eightBitLut": "matte_paint",
            "viewerLut": project.viewer_lut,
            "workingSpace": "scene_linear",
            "thumbnailLut": "ACES/Rec.709",
            "linkTrackItemVersions": "1",
            "redVideoDecodeMode": "0",
            "customExportRootPath": "",
            "ocioconfigpath": "",
            "editable": "1",
        }
        project_el = ET.SubElement(root, "Project", attrs)
        sequences_guid, tags_guid = self._build_project_items(project_el)
        width, height = self._project_resolution()
        ET.SubElement(project_el, "BinViewType").text = "2"
        ET.SubElement(project_el, "BinViewZoom").text = "70"
        ET.SubElement(project_el, "BinViewSortColumnIndex").text = "0"
        ET.SubElement(project_el, "BinViewSortOrder").text = "0"
        ET.SubElement(project_el, "AllowedItems").text = "-1"
        ET.SubElement(
            project_el,
            "RootBinProjectItem",
            {"objName": "sequencesBin", "link": "internal", "guid": sequences_guid},
        )
        ET.SubElement(
            project_el,
            "RootBinProjectItem",
            {"objName": "tagsBin", "link": "internal", "guid": tags_guid},
        )
        ET.SubElement(
            project_el,
            "MediaFormatValue",
            {
                "objName": "outputformat",
                "name": "",
                "value": f"1,[ 0, 0, {width}, {height}],[ 0, 0, {width}, {height}],Custom Format",
                "default": "0",
            },
        )
        views_el = ET.SubElement(project_el, "Views")
        ET.SubElement(views_el, "View", {"name": "main", "color": "#ffffff"})

    def _build_ui_state(self, root) -> None:
        if not (self.master_sequence_guid and self.master_sequence_version_guid):
            return
        ui_state = ET.SubElement(root, "UIState")
        items_el = ET.SubElement(ui_state, "items")
        viewer_el = ET.SubElement(
            items_el,
            "Viewer",
            {
                "audioLevel": "50",
                "time": "0",
                "audioLatencyMs": "0",
                "audioMute": "0",
                "objectname": "uk.co.thefoundry.sequenceviewer.1",
                "mode": "0",
            },
        )
        players_el = ET.SubElement(viewer_el, "players")
        primary_player = ET.SubElement(
            players_el,
            "player",
            {
                "repeatMode": "2",
                "time": "0",
                "LUT": "ACES/Rec.709",
                "channels": "0",
                "translateX": "0",
                "translateY": "0",
                "lod": "-1",
                "playSpeed": "1",
                "scaleX": "0.5",
                "rotate": "0",
                "displayGamma": "1",
                "zoomMode": "2",
                "scaleY": "0.5",
                "displayGain": "1",
            },
        )
        ET.SubElement(
            primary_player,
            "Sequence",
            {"guid": self.master_sequence_guid, "link": "internal", "objName": "timeline"},
        )
        ET.SubElement(
            players_el,
            "player",
            {
                "repeatMode": "0",
                "time": "0",
                "LUT": "ACES/Rec.709",
                "channels": "0",
                "translateX": "0",
                "translateY": "0",
                "lod": "-1",
                "playSpeed": "1",
                "scaleX": "0.25",
                "rotate": "0",
                "displayGamma": "1",
                "zoomMode": "2",
                "scaleY": "0.25",
                "displayGain": "1",
            },
        )
        timeline_editor = ET.SubElement(
            items_el,
            "TimelineEditor",
            {"objectname": "uk.co.thefoundry.timeline.1", "lastVisibleTime": str(self._sequence_duration()), "firstVisibleTime": "0"},
        )
        ET.SubElement(
            timeline_editor,
            "SequenceProjectItemVersion",
            {"guid": self.master_sequence_version_guid, "link": "internal", "objName": "timeline"},
        )
        viewer_ref_guid = _braced_uuid()
        ET.SubElement(
            timeline_editor,
            "Viewer",
            {"guid": viewer_ref_guid, "link": "internal", "objName": "viewer"},
        )

    def _build_project_items(self, project_el) -> Tuple[str, str]:
        items_el = ET.SubElement(project_el, "items")
        sequences_guid = _braced_uuid()
        sequences_root = ET.SubElement(
            items_el,
            "RootBinProjectItem",
            {"name": "Sequences", "guid": sequences_guid, "editable": "1"},
        )
        self._append_bin_metadata(sequences_root, allowed_items="13")
        sequences_items = ET.SubElement(sequences_root, "items")

        plates_guid = _braced_uuid()
        plates_bin = ET.SubElement(
            sequences_items,
            "BinProjectItem",
            {"name": "plates", "guid": plates_guid, "editable": "1"},
        )
        self._append_bin_metadata(plates_bin)
        plates_items = ET.SubElement(plates_bin, "items")
        self._build_sequence_project_item(plates_items)
        self._build_clip_bins(plates_items)

        tags_guid = _braced_uuid()
        tags_root = ET.SubElement(
            items_el,
            "RootBinProjectItem",
            {"name": "Tags", "guid": tags_guid, "editable": "1"},
        )
        self._append_bin_metadata(tags_root, allowed_items="17")

        return sequences_guid, tags_guid

    def _build_clip_bins(self, parent) -> None:
        episode_bins: Dict[str, ET.Element] = {}
        scene_bins: Dict[Tuple[str, str], ET.Element] = {}
        for record in self.track_items:
            episode = record.context.episode
            scene = record.context.scene
            episode_items = episode_bins.get(episode)
            if episode_items is None:
                episode_bin = ET.SubElement(
                    parent,
                    "BinProjectItem",
                    {"name": episode, "guid": _braced_uuid(), "editable": "1"},
                )
                self._append_bin_metadata(episode_bin)
                episode_items = ET.SubElement(episode_bin, "items")
                episode_bins[episode] = episode_items
            scene_key = (episode, scene)
            scene_items = scene_bins.get(scene_key)
            if scene_items is None:
                scene_bin = ET.SubElement(
                    episode_items,
                    "BinProjectItem",
                    {
                        "name": f"{episode}_{scene}",
                        "guid": _braced_uuid(),
                        "editable": "1",
                    },
                )
                self._append_bin_metadata(scene_bin)
                scene_items = ET.SubElement(scene_bin, "items")
                scene_bins[scene_key] = scene_items
            self._build_clip_project_item(scene_items, record)

    def _build_clip_project_item(self, parent, record: TrackItemRecord) -> None:
        display_name = record.clip_name
        root_guid = _braced_uuid()
        version_guid = _braced_uuid()
        project_item_root = ET.SubElement(
            parent,
            "SequenceProjectItemRoot",
            {
                "name": f"{display_name} Copy",
                "guid": root_guid,
                "MasterVersion": record.source.path.as_posix(),
                "editable": "1",
            },
        )
        items_el = ET.SubElement(project_item_root, "items")
        version_el = ET.SubElement(
            items_el,
            "SequenceProjectItemVersion",
            {
                "name": display_name,
                "guid": version_guid,
                "isHidden": "0",
                "editable": "1",
            },
        )
        ET.SubElement(
            version_el,
            "Clip",
            {"guid": record.clip_guid, "link": "internal", "objName": "sequence"},
        )
        ET.SubElement(
            project_item_root,
            "Clip",
            {"guid": record.clip_guid, "link": "internal", "objName": "sequence"},
        )
        ET.SubElement(project_item_root, "ActiveItemIndex").text = "0"
        ET.SubElement(project_item_root, "TimelineProjectItem", {"objName": "Snapshots", "name": "", "editable": "1"})

    def _build_sequence_project_item(self, parent) -> None:
        naming = self.naming
        project = self.input.project
        master_version = self.input.clips[0].file_path.as_posix() if self.input.clips else ""
        sequence_root_guid = _braced_uuid()
        sequence_guid = _braced_uuid()
        version_guid = _braced_uuid()
        sequence_root = ET.SubElement(
            parent,
            "SequenceProjectItemRoot",
            {
                "name": naming.episode,
                "guid": sequence_root_guid,
                "MasterVersion": master_version,
                "editable": "1",
            },
        )
        sequence_items = ET.SubElement(sequence_root, "items")
        version_el = ET.SubElement(
            sequence_items,
            "SequenceProjectItemVersion",
            {"name": naming.episode, "guid": version_guid, "isHidden": "0", "editable": "1"},
        )
        sequence_attrs = {
            "timeOffset": "0",
            "displayTimecode": "1",
            "objName": "sequence",
            "name": naming.episode,
            "timecodeStart": str(project.timecode_start),
            "displayDropFrames": "0",
            "useSoftTrims": "0",
            "guid": sequence_guid,
            "timeDisplayFormat": "0",
        }
        sequence_el = ET.SubElement(version_el, "Sequence", sequence_attrs)
        self._populate_sequence_tracks(sequence_el)
        self._populate_sequence_audio(sequence_el)
        self._populate_sequence_sets(sequence_el)

        ET.SubElement(
            sequence_root,
            "Sequence",
            {"objName": "sequence", "link": "internal", "guid": sequence_guid},
        )
        ET.SubElement(sequence_root, "ActiveItemIndex").text = "0"
        ET.SubElement(sequence_root, "TimelineProjectItem", {"objName": "Snapshots", "name": "", "editable": "1"})
        self.master_sequence_root_guid = sequence_root_guid
        self.master_sequence_guid = sequence_guid
        self.master_sequence_version_guid = version_guid

    def _populate_sequence_tracks(self, sequence_el) -> None:
        video_tracks_el = ET.SubElement(sequence_el, "videotracks")
        track_info = self.track_state.get(self.primary_track)
        track_guid = track_info["guid"] if track_info else _braced_uuid()
        track_el = ET.SubElement(
            video_tracks_el,
            "VideoTrack",
            {
                "name": self.primary_track,
                "height": "40",
                "guid": track_guid,
                "collapsed": "0",
            },
        )
        track_items_el = ET.SubElement(track_el, "trackItems")
        for record in track_info["items"] if track_info else []:
            ET.SubElement(track_items_el, "TrackItem", {"link": "internal", "guid": record.guid})
        self._add_track_enabled_set(track_el)

    def _populate_sequence_audio(self, sequence_el) -> None:
        audio_tracks_el = ET.SubElement(sequence_el, "audiotracks")
        audio_track_el = ET.SubElement(
            audio_tracks_el,
            "AudioTrack",
            {
                "name": "Audio 1",
                "guid": _braced_uuid(),
                "height": "40",
                "collapsed": "0",
                "stereochannel": "left",
                "volume": "1",
            },
        )
        self._add_track_enabled_set(audio_track_el)

    def _populate_sequence_sets(self, sequence_el) -> None:
        project = self.input.project
        duration = self._sequence_duration()
        sets_el = ET.SubElement(sequence_el, "sets")
        set_el = ET.SubElement(sets_el, "Set", {"title": "Timeline", "domainroot": "foundry.timeline"})
        values_el = ET.SubElement(set_el, "values")
        ET.SubElement(
            values_el,
            "TimeBaseValue",
            {"name": "foundry.timeline.framerate", "value": project.framerate_str, "default": "1"},
        )
        ET.SubElement(
            values_el,
            "TimeBaseValue",
            {"name": "foundry.timeline.samplerate", "value": project.samplerate_str, "default": "1"},
        )
        ET.SubElement(
            values_el,
            "IntegerValue",
            {"name": "foundry.timeline.duration", "value": str(duration), "default": "0"},
        )
        ET.SubElement(
            values_el,
            "IntegerValue",
            {"name": "foundry.timeline.poster", "value": "0", "default": "1"},
        )
        ET.SubElement(
            values_el,
            "StringValue",
            {"name": "foundry.timeline.posterLayer", "value": "colour", "default": "1"},
        )
        width, height = self._project_resolution()
        ET.SubElement(
            values_el,
            "MediaFormatValue",
            {
                "name": "foundry.timeline.outputformat",
                "value": f"1,[ 0, 0, {width}, {height}],[ 0, 0, {width}, {height}],Custom Format",
                "default": "1",
            },
        )

    def _append_bin_metadata(self, element, allowed_items: Optional[str] = None) -> None:
        ET.SubElement(element, "BinViewType").text = "2"
        ET.SubElement(element, "BinViewZoom").text = "70"
        ET.SubElement(element, "BinViewSortColumnIndex").text = "0"
        ET.SubElement(element, "BinViewSortOrder").text = "0"
        if allowed_items is not None:
            ET.SubElement(element, "AllowedItems").text = allowed_items

    def _add_track_enabled_set(self, track_el) -> None:
        sets_el = ET.SubElement(track_el, "sets")
        set_el = ET.SubElement(sets_el, "Set", {"title": "Track", "domainroot": "foundry.track"})
        values_el = ET.SubElement(set_el, "values")
        ET.SubElement(values_el, "BooleanValue", {"name": "foundry.track.enabled", "value": "Yes", "default": "1"})

    def _project_resolution(self) -> Tuple[int, int]:
        for record in self.sources.values():
            meta = record.metadata
            if meta and meta.width and meta.height:
                return meta.width, meta.height
        return (2048, 1152)

    def _sequence_duration(self) -> int:
        track = self.track_state.get(self.primary_track)
        if not track:
            return 0
        max_frame = 0
        for record in track["items"]:
            max_frame = max(max_frame, record.timeline_in + record.timeline_duration)
        return max_frame


    def _build_track_item_collection(self, root) -> None:
        collection_el = ET.SubElement(root, "trackItemCollection")
        for record in self.track_items:
            self._build_timeline_track_item(collection_el, record)
            self._build_source_track_item(collection_el, record)

    def _build_timeline_track_item(self, collection_el, record: TrackItemRecord) -> None:
        attrs = {
            "guid": record.guid,
            "name": f"{record.clip_name} Copy",
            "playbackSpeed": "1",
            "streamIndex": "-1",
            "boxSizeHeight": "200",
            "channelIndex": "0",
            "boxSizeWidth": "200",
            "timelineDuration": str(record.timeline_duration),
            "resizeType": "1",
            "resizeCenter": "1",
            "clipSequenceTrackIndex": "0",
            "conformScore": "0",
            "timelineIn": str(record.timeline_in),
            "type": "0",
            "matchdescription": "",
            "boxForceShape": "0",
            "sourceIn": "0",
            "boxPAR": "1",
            "versionlinked": "1",
            "enabled": "1",
            "sourceDuration": str(record.timeline_duration),
            "outputChannel": "-2",
        }
        track_item_el = ET.SubElement(collection_el, "TrackItem", attrs)
        self._attach_link_group(track_item_el, record.timeline_link_group_guid)
        ET.SubElement(track_item_el, "MediaFlags", {"objName": "flags", "allone": "1"})
        ET.SubElement(track_item_el, "MediaType", {"objName": "type", "type": "0"})
        look_el = ET.SubElement(track_item_el, "Look", {"objName": "look"})
        ET.SubElement(look_el, "CompositeEffect", {"objName": "effects"})
        media_desc = ET.SubElement(
            track_item_el,
            "MediaDesc",
            {"channelIndex": "0", "objName": "mediatype", "streamIndex": "-1", "outputChannel": "-2"},
        )
        ET.SubElement(media_desc, "MediaFlags", {"objName": "flags", "allone": "1"})
        ET.SubElement(media_desc, "MediaType", {"objName": "type", "type": "0"})
        media_group = ET.SubElement(track_item_el, "MediaGroup", {"objName": "media"})
        group_data = ET.SubElement(media_group, "groupdata")
        media_vector = ET.SubElement(group_data, "MediaInstance_Vector", {"quality": "0"})
        ET.SubElement(media_vector, "Clip", {"objName": "media", "link": "internal", "guid": record.clip_guid})

    def _build_source_track_item(self, collection_el, record: TrackItemRecord) -> None:
        attrs = {
            "guid": record.source_track_item_guid,
            "name": record.clip_name,
            "playbackSpeed": "1",
            "streamIndex": "-1",
            "boxSizeHeight": "200",
            "channelIndex": "0",
            "boxSizeWidth": "200",
            "timelineDuration": str(record.source_duration),
            "resizeType": "1",
            "resizeCenter": "1",
            "clipSequenceTrackIndex": "0",
            "conformScore": "0",
            "timelineIn": "0",
            "type": "1",
            "matchdescription": "",
            "boxForceShape": "0",
            "sourceIn": str(record.source_in),
            "boxPAR": "1",
            "versionlinked": "0",
            "enabled": "1",
            "sourceDuration": str(record.source_duration),
            "outputChannel": "-2",
        }
        track_item_el = ET.SubElement(collection_el, "TrackItem", attrs)
        self._attach_link_group(track_item_el, record.source_link_group_guid)
        ET.SubElement(track_item_el, "MediaFlags", {"objName": "flags", "allone": "1"})
        ET.SubElement(track_item_el, "MediaType", {"objName": "type", "type": "0"})
        look_el = ET.SubElement(track_item_el, "Look", {"objName": "look"})
        ET.SubElement(look_el, "CompositeEffect", {"objName": "effects"})
        media_desc = ET.SubElement(
            track_item_el,
            "MediaDesc",
            {"channelIndex": "0", "objName": "mediatype", "streamIndex": "-1", "outputChannel": "-2"},
        )
        ET.SubElement(media_desc, "MediaFlags", {"objName": "flags", "allone": "1"})
        ET.SubElement(media_desc, "MediaType", {"objName": "type", "type": "0"})
        media_group = ET.SubElement(track_item_el, "MediaGroup", {"objName": "media"})
        group_data = ET.SubElement(media_group, "groupdata")
        media_vector = ET.SubElement(group_data, "MediaInstance_Vector", {"quality": "0"})
        ET.SubElement(media_vector, "Source", {"objName": "media", "link": "internal", "guid": record.source.guid})

    def _attach_link_group(self, track_item_el, link_guid: str) -> None:
        link_group = ET.SubElement(
            track_item_el,
            "TrackItemLinkGroup",
            {"guid": link_guid, "link": "internal", "objName": "links"},
        )


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return _format_float(value)
    return str(value)


def _format_float(value: float) -> str:
    text = f"{value:.6f}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _split_ratio(text: Optional[str]) -> Tuple[int, int]:
    if not text:
        return 25, 1
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            numerator = max(1, int(left))
            denominator = max(1, int(right))
            return numerator, denominator
        except ValueError:
            pass
    try:
        value = float(text)
    except (TypeError, ValueError):
        return 25, 1
    return max(1, int(round(value))), 1


def _format_path(path: Path, options: GenerationOptions) -> str:
    candidate = path
    if options.path_base:
        try:
            candidate = path.relative_to(options.path_base)
        except ValueError:
            candidate = path
    text = candidate.as_posix()
    if options.use_relative_paths and options.output_path:
        try:
            rel = os.path.relpath(path, options.output_path.parent)
            text = rel.replace("\\", "/")
        except ValueError:
            pass
    return text


def _write_tree(root, out_path: Path) -> None:
    if HAVE_LXML:
        xml_bytes = ET.tostring(
            root,
            encoding="UTF-8",
            pretty_print=True,
            xml_declaration=True,
            doctype="<!DOCTYPE hieroXML>",
        )
        out_path.write_bytes(xml_bytes)
    else:
        _indent(root)
        xml_bytes = ET.tostring(root, encoding="unicode")
        header = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE hieroXML>\n"
        out_path.write_text(header + xml_bytes, encoding="utf-8")


def _indent(elem, level: int = 0) -> None:
    indent = "  "
    i = "\n" + level * indent
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + indent
        for child in elem:
            _indent(child, level + 1)
        last_child = elem[-1]
        if not last_child.tail or not last_child.tail.strip():
            last_child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def _braced_uuid() -> str:
    return "{" + str(uuid.uuid4()) + "}"
