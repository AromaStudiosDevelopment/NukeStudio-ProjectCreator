from pathlib import Path
import json
import xml.etree.ElementTree as ET

from hrox_generator.generator import GenerationOptions, generate_hrox
from hrox_generator.schema import load_input


def test_generate_hrox_minimal(tmp_path):
    plate_path = tmp_path / "plate.mov"
    plate_path.write_bytes(b"fake")
    schema = {
        "project": {
            "name": "Example",
            "framerate": "25/1",
            "samplerate": "48000/1",
            "timecodeStart": 90000,
        },
        "tracks": [
            {"name": "pl01", "kind": "video"},
            {"name": "Video 1", "kind": "video"},
            {"name": "VFX 1", "kind": "video"},
        ],
        "clips": [
            {
                "file": str(plate_path),
                "track": "Video 1",
                "timelineIn": 0,
                "sourceDuration": 12,
            },
            {
                "file": str(plate_path),
                "track": "VFX 1",
                "timelineIn": 0,
                "sourceDuration": 12,
            },
        ],
    }
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    data = load_input(schema_path)
    out_path = tmp_path / "out.hrox"
    report = generate_hrox(
        data,
        out_path,
        options=GenerationOptions(dry_run=False, strict_paths=True),
    )

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    root = ET.fromstring(content)
    project_el = root.find("Project")
    assert project_el is not None
    scene_bin = project_el.find(".//BinProjectItem[@name='ep000_sc000_default']")
    assert scene_bin is not None
    clip_project_item = scene_bin.find(".//SequenceProjectItemRoot")
    assert clip_project_item is not None
    master_sequence = project_el.find(".//SequenceProjectItemRoot[@name='ep000']")
    assert master_sequence is not None
    video_track = root.find(".//Sequence//VideoTrack[@name='pl01']")
    assert video_track is not None
    media_clips = root.findall("./Media/Clip")
    assert media_clips, "expected clip entries under <Media>"
    timeline_track_items = root.findall("./trackItemCollection/TrackItem[@type='0']")
    source_track_items = root.findall("./trackItemCollection/TrackItem[@type='1']")
    assert timeline_track_items and source_track_items
    link_groups = root.findall("./TrackItemLinkGroups/TrackItemLinkGroup")
    assert link_groups, "link groups should be serialized"
    assert any("guid" in entry for entry in report.sources)


def test_timeline_offsets_stack_even_with_zero_input(tmp_path):
    plate_path = tmp_path / "plate.mov"
    plate_path.write_bytes(b"fake")
    schema = {
        "project": {
            "name": "Example",
            "framerate": "25/1",
            "samplerate": "48000/1",
            "timecodeStart": 90000,
        },
        "tracks": [{"name": "pl01", "kind": "video"}],
        "clips": [
            {
                "file": str(plate_path),
                "track": "pl01",
                "timelineIn": 0,
                "sourceDuration": 10,
            },
            {
                "file": str(plate_path),
                "track": "pl01",
                "timelineIn": 0,
                "sourceDuration": 15,
            },
        ],
    }
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    data = load_input(schema_path)
    out_path = tmp_path / "stacked.hrox"
    generate_hrox(data, out_path, options=GenerationOptions(strict_paths=True))

    content = out_path.read_text(encoding="utf-8")
    root = ET.fromstring(content)
    timeline_items = root.findall("./trackItemCollection/TrackItem[@type='0']")
    assert [item.get("timelineIn") for item in timeline_items] == ["0", "10"]
    duration_value = root.find(
        ".//Sequence//Set[@title='Timeline']/values/IntegerValue[@name='foundry.timeline.duration']"
    )
    assert duration_value is not None
    assert duration_value.get("value") == "25"
