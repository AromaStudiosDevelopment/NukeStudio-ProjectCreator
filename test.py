#!/usr/bin/env python3
"""
Generate a minimal .hrox (hieroXML) project for Nuke Studio / Hiero.
Requires: Python 3.x, ffprobe (optional, to get frame counts)
"""

import xml.etree.ElementTree as ET
from uuid import uuid4
from pathlib import Path
import subprocess
import json

# ---------- helpers ----------
def braced_uuid():
    return "{" + str(uuid4()) + "}"

def ffprobe_framecount(path):
    """
    Returns frame count for video using ffprobe (best-effort).
    Requires ffprobe in PATH. Returns int or None if failed.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-count_frames", "-select_streams", "v:0",
        "-print_format", "json",
        "-show_entries", "stream=nb_read_frames",
        str(path)
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        j = json.loads(out)
        streams = j.get("streams") or []
        if streams and "nb_read_frames" in streams[0]:
            return int(streams[0]["nb_read_frames"])
    except Exception:
        # fallback try: get duration and estimate by fps (not as reliable)
        try:
            cmd2 = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,duration", "-of", "json", str(path)]
            out2 = subprocess.check_output(cmd2, stderr=subprocess.STDOUT)
            j2 = json.loads(out2)
            s = j2.get("streams", [{}])[0]
            dur = float(s.get("duration") or 0.0)
            fr_str = s.get("avg_frame_rate", "25/1")
            num, den = fr_str.split("/")
            fps = float(num)/float(den)
            return int(round(dur * fps))
        except Exception:
            return None

# ---------- inputs ----------
# Example: list of media files and target timeline placements (frames)
# If you don't have timelineIn, the script will append clips sequentially.
media_files = [
    r"D:/VFX_Projects/2024/Drama/PRESTIGE/Footage/Prestige_ep008_sc111_face_replacment_sh0010_pl01_v01.mov",
    r"D:/VFX_Projects/2024/Drama/PRESTIGE/Footage/Prestige_ep008_sc111_face_replacment_sh0030_pl01_v01.mov",
]
project_name = "Generated_HieroProject"
framerate = (25, 1)  # numer, den
timecode_start_frames = 90000  # same style as original (01:00:00 at 25fps)
audio_samplerate = "48000/1"

# ---------- build XML ----------
root_attrib = {
    "name": "NukeStudio",  # preserve consumer name
    "version": "11",
    "revision": "0",
    "release": "12.2v2"
}
root = ET.Element("hieroXML", root_attrib)

# Media block
media_block = ET.SubElement(root, "Media")
media_guid_map = {}
for path_str in media_files:
    p = Path(path_str)
    guid = braced_uuid()
    # try to get frames
    frames = ffprobe_framecount(p)
    # if failed, leave out duration (not mandatory in minimal case)
    attrs = {"file": str(p), "name": p.name, "guid": guid}
    if frames is not None:
        attrs["duration"] = str(frames)
    ET.SubElement(media_block, "Source", attrs)
    media_guid_map[path_str] = guid

# Project block (minimal set)
project_attrs = {
    "project_directory": "",
    "samplerate": audio_samplerate,
    "framerate": f"{framerate[0]}/{framerate[1]}",
    "name": project_name,
    "guid": braced_uuid(),
    "viewerLut": "ACES/Rec.709",
    "ocioConfigName": "aces_1.2",
    "timecodeStart": str(timecode_start_frames),
}
ET.SubElement(root, "Project", project_attrs)

# trackItemCollection - create TrackItem per media
tic = ET.SubElement(root, "trackItemCollection")
trackitem_map = {}
cursor = 0
for path_str in media_files:
    guid = braced_uuid()
    # read duration back from media source if available (we used ffprobe earlier)
    frames = None
    # lookup duration in Media Source element if present
    for src in media_block.findall("Source"):
        if src.attrib.get("file") == path_str:
            frames = src.attrib.get("duration")
            break
    timelineIn = str(cursor)
    timelineDuration = str(frames or 0)
    ti_attrib = {
        "guid": guid,
        "name": Path(path_str).stem,
        "timelineIn": timelineIn,
        "timelineDuration": timelineDuration,
        "sourceIn": "0",
        "sourceDuration": timelineDuration,
        "outputChannel": "-2",
        "versionlinked": "0",
    }
    ti = ET.SubElement(tic, "TrackItem", ti_attrib)
    # a minimal MediaGroup linking back to media Source GUID
    mg = ET.SubElement(ti, "MediaGroup", {"objName":"media"})
    groupdata = ET.SubElement(mg, "groupdata")
    mi = ET.SubElement(groupdata, "MediaInstance_Vector", {"quality":"0"})
    ET.SubElement(mi, "Source", {"objName":"media", "link":"internal", "guid": media_guid_map[path_str]})
    trackitem_map[path_str] = guid
    # advance cursor (place sequentially)
    cursor += int(frames or 0)

# Very simple Sequence element with one VideoTrack referencing those TrackItem GUIDs
seq = ET.SubElement(root, "Sequence", {"timeOffset":"0", "displayTimecode":"1", "name":"Sequence 1", "timecodeStart": str(timecode_start_frames)})
vt = ET.SubElement(seq, "videotracks")
video_track = ET.SubElement(vt, "VideoTrack", {"name":"Video 1", "height":"40", "guid": braced_uuid(), "collapsed":"0"})
trackitems = ET.SubElement(video_track, "trackItems")
for path_str in media_files:
    ET.SubElement(trackitems, "TrackItem", {"link":"internal", "guid": trackitem_map[path_str]})

# ---------- write to file including DOCTYPE ----------
out_path = Path("GeneratedProject.hrox")
xml_header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE hieroXML>\n'
xml_body = ET.tostring(root, encoding="utf-8").decode("utf-8")

with out_path.open("w", encoding="utf-8") as fh:
    fh.write(xml_header)
    fh.write(xml_body)

print("Wrote", out_path)
