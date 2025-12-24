import json

import hrox_generator.ffprobe as ffprobe


def test_get_frame_count_prefers_count(monkeypatch, tmp_path):
    payload = json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "nb_read_frames": "42",
                    "avg_frame_rate": "25/1",
                    "width": 1920,
                    "height": 1080,
                    "tags": {"timecode": "00:00:00:00"},
                }
            ],
            "format": {"duration": "1.68", "size": "100"},
        }
    )

    plate_path = tmp_path / "dummy.mov"
    plate_path.write_bytes(b"fake")

    def fake_check_output(cmd, stderr=None, timeout=None):  # noqa: ARG001 - signature compat
        return payload.encode("utf-8")

    monkeypatch.setattr(ffprobe.subprocess, "check_output", fake_check_output)
    result = ffprobe.get_frame_count(plate_path, ffprobe_path="ffprobe")
    assert result.frames == 42
    assert result.method == "count_frames"
    assert result.metadata is not None
    assert result.metadata.width == 1920


def test_get_frame_count_falls_back(monkeypatch, tmp_path):
    payload = json.dumps(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "2.0",
                    "avg_frame_rate": "24/1",
                    "width": 1024,
                    "height": 576,
                }
            ],
            "format": {"duration": "2.0", "size": "50"},
        }
    )

    plate_path = tmp_path / "dummy.mov"
    plate_path.write_bytes(b"fake")

    def fake_check_output(cmd, stderr=None, timeout=None):  # noqa: ARG001
        return payload.encode("utf-8")

    monkeypatch.setattr(ffprobe.subprocess, "check_output", fake_check_output)
    result = ffprobe.get_frame_count(plate_path, ffprobe_path="ffprobe")
    assert result.frames == 48
    assert result.method == "rate_estimate"
