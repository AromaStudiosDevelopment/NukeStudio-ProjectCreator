from pathlib import Path

import json
import pytest

from hrox_generator.schema import InputData, SchemaValidationError, load_input


def test_load_input_roundtrip(tmp_path):
    payload = {
        "project": {
            "name": "TestProject",
            "framerate": "25/1",
            "samplerate": "48000/1",
            "timecodeStart": 90000,
        },
        "tracks": [{"name": "Video 1", "kind": "video"}],
        "clips": [
            {
                "file": str(tmp_path / "plate.mov"),
                "track": "Video 1",
                "timelineIn": 0,
                "sourceDuration": 10,
            }
        ],
    }
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(payload), encoding="utf-8")

    data = load_input(schema_path)
    assert isinstance(data, InputData)
    assert data.project.framerate == (25, 1)
    assert data.tracks[0].name == "Video 1"
    assert data.clips[0].timeline_in == 0


def test_load_input_rejects_unknown_track(tmp_path):
    payload = {
        "project": {
            "name": "TestProject",
            "framerate": "25/1",
            "samplerate": "48000/1",
            "timecodeStart": 90000,
        },
        "tracks": [{"name": "Video 1"}],
        "clips": [
            {
                "file": str(tmp_path / "plate.mov"),
                "track": "Video 2",
            }
        ],
    }
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SchemaValidationError):
        load_input(schema_path)
