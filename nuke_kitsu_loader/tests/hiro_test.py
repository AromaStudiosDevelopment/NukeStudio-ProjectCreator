"""Utility helpers for testing Hiero EXR imports and loading Nuke workfiles.

Adds two reusable functions:
- load_plates(location)  -- (existing) import EXR image sequence folder into a "footage" bin
  and create a sequence "generated_timeline" with a video track "pl01" and place the clip.

- load_workfile(workfile, sequence=None) -- (new) import a Nuke .nk workfile into a "scripts" bin
  and place a reference clip into the same sequence (default: "generated_timeline") on a track
  named "comp". The function will attempt to create a Clip from the provided path; if Hiero
  does not recognise the file as a playable media source, a placeholder TrackItem with the
  script path saved as metadata is created instead (so the workfile is still stored in the
  project's Bin and visible on the timeline for organisational purposes).

Note: This file is written to work with Hiero's Python API (Hiero 12 series). The API is
documented in The Foundry's Hiero Python Developer Guide. Behaviour for non-media files
is implementation-dependent across Hiero versions; the function below includes fallbacks.
"""

import os
import hiero.core


def load_plates(location):
    """Import plate media at *location* into a Hiero project and timeline.

    Returns a dictionary with references to useful objects for downstream use.
    """
    if not location:
        raise ValueError("location must be provided")

    normalized_path = hiero.core.remapPath(os.path.normpath(location))

    projects = hiero.core.projects()
    if projects:
        proj = projects[-1]
    else:
        proj = hiero.core.newProject()

    top_clips_bin = proj.clipsBin()
    existing = [b for b in top_clips_bin.items() if isinstance(b, hiero.core.Bin) and b.name() == "footage"]
    if existing:
        footage_bin = existing[0]
    else:
        footage_bin = hiero.core.Bin("footage")
        top_clips_bin.addItem(footage_bin)

    print("Using Bin: %s" % (footage_bin.name(),))

    try:
        imported_result = footage_bin.importFolder(normalized_path)
        print("Import completed for: %s" % normalized_path)
    except Exception as exc:
        print("Import failed: %s" % (exc,))
        raise

    sequence_binitems = footage_bin.sequences()
    clip_binitems = footage_bin.clips()

    source_obj = None
    if sequence_binitems:
        source_obj = sequence_binitems[0].activeItem()
        print("Found imported Sequence: %s" % (sequence_binitems[0].name(),))
    elif clip_binitems:
        source_obj = clip_binitems[0].activeItem()
        print("Found imported Clip: %s" % (clip_binitems[0].name(),))
    elif isinstance(imported_result, hiero.core.Bin) and imported_result is not footage_bin:
        seqs = imported_result.sequences()
        clips = imported_result.clips()
        if seqs:
            source_obj = seqs[0].activeItem()
            print("Found imported Sequence in returned bin: %s" % (seqs[0].name(),))
        elif clips:
            source_obj = clips[0].activeItem()
            print("Found imported Clip in returned bin: %s" % (clips[0].name(),))

    if source_obj is None:
        raise RuntimeError("No sequence or clip found in '%s' after import." % normalized_path)

    # create or reuse a sequence named "generated_timeline"
    seq_name = "generated_timeline"
    # check if project already has this sequence in the clips bin
    existing_seq_items = [si for si in proj.clipsBin().sequences() if si.name() == seq_name]
    if existing_seq_items:
        new_sequence = existing_seq_items[0].activeItem()
        print("Using existing Sequence: %s" % (new_sequence.name(),))
    else:
        new_sequence = hiero.core.Sequence(seq_name)
        proj.clipsBin().addItem(hiero.core.BinItem(new_sequence))
        print("Created Sequence: %s" % (new_sequence.name(),))

    # create or reuse 'pl01' video track
    track_name = "pl01"
    existing_video_tracks = [t for t in new_sequence.videoTracks() if t.name() == track_name]
    if existing_video_tracks:
        video_track = existing_video_tracks[0]
    else:
        video_track = hiero.core.VideoTrack(track_name)
        new_sequence.addTrack(video_track)
        print("Added VideoTrack '%s' to Sequence '%s'." % (video_track.name(), new_sequence.name()))

    # add to sequence
    try:
        # find track index
        track_index = list(new_sequence.videoTracks()).index(video_track)
        new_sequence.addClip(source_obj, 0, videoTrackIndex=track_index)
        print("Added imported media to timeline '%s' on track '%s'." % (new_sequence.name(), video_track.name()))
    except Exception as exc:
        print("addClip failed (%s). Trying manual TrackItem creation..." % (exc,))
        track_item = video_track.createTrackItem(source_obj.name())
        track_item.setSource(source_obj)
        track_item.setTimelineIn(0)
        track_item.setTimelineOut(track_item.sourceDuration() - 1)
        video_track.addItem(track_item)
        print("Fallback: manually created TrackItem and added to track.")

    print("Done. Check the Project Bin for 'footage' and the Sequence 'generated_timeline'.")

    return {
        "project": proj,
        "footage_bin": footage_bin,
        "sequence": new_sequence,
        "video_track": video_track,
        "source": source_obj,
    }


def load_workfile(workfile, sequence=None):
    """Import a Nuke workfile (.nk) into a 'scripts' bin and place it on a 'comp' track.

    Args:
        workfile (str): path to the .nk file (UNC or local path).
        sequence (hiero.core.Sequence or None): Sequence to load into. If None the function
            will look for 'generated_timeline' in the current project and create it if missing.

    Returns:
        dict: references to project, scripts_bin, sequence, comp_track and the created track_item.

    Behaviour notes:
    - The function attempts to create a hiero.core.Clip(workfile). If Hiero treats the .nk
      as a valid MediaSource, this will create a playable Clip and add it to the timeline.
    - If Clip creation fails (common for .nk), the function creates a placeholder TrackItem
      and stores the absolute workfile path on that TrackItem using the item's metadata API
      (if available). This guarantees the workfile is visible and findable inside Hiero.

    """
    if not workfile:
        raise ValueError("workfile path must be provided")

    normalized_wf = hiero.core.remapPath(os.path.normpath(workfile))

    projects = hiero.core.projects()
    if projects:
        proj = projects[-1]
    else:
        proj = hiero.core.newProject()

    # get or create scripts bin
    top_clips_bin = proj.clipsBin()
    existing = [b for b in top_clips_bin.items() if isinstance(b, hiero.core.Bin) and b.name() == "scripts"]
    if existing:
        scripts_bin = existing[0]
    else:
        scripts_bin = hiero.core.Bin("scripts")
        top_clips_bin.addItem(scripts_bin)

    print("Using Scripts Bin: %s" % (scripts_bin.name(),))

    # Attempt to create a Clip from the workfile path. In many Hiero versions this will raise or
    # create a Clip that contains an unrecognised MediaSource. We handle both cases.
    clip_obj = None
    created_binitem = None
    try:
        clip_obj = hiero.core.Clip(normalized_wf)
        created_binitem = hiero.core.BinItem(clip_obj)
        scripts_bin.addItem(created_binitem)
        print("Created Clip for workfile and added to 'scripts' bin: %s" % (normalized_wf,))
    except Exception as exc:
        # fallback: create a non-playable BinItem entry by using a minimal Clip wrapper
        print("Could not create Clip from workfile (%s). Falling back to placeholder bin entry. Error: %s" % (normalized_wf, exc))
        # create a tiny sequence to wrap as BinItem (zero-length) so it can be placed on timeline.
        # Name it after the workfile for clarity.
        placeholder_seq = hiero.core.Sequence(os.path.basename(normalized_wf))
        created_binitem = hiero.core.BinItem(placeholder_seq)
        scripts_bin.addItem(created_binitem)
        clip_obj = None

    # find or create target sequence
    target_sequence = None
    if sequence is not None:
        target_sequence = sequence
    else:
        seq_name = "generated_timeline"
        seq_items = [si for si in proj.clipsBin().sequences() if si.name() == seq_name]
        if seq_items:
            target_sequence = seq_items[0].activeItem()
        else:
            target_sequence = hiero.core.Sequence(seq_name)
            proj.clipsBin().addItem(hiero.core.BinItem(target_sequence))
            print("Created Sequence: %s" % (target_sequence.name(),))

    # create or get comp track
    comp_name = "comp"
    existing_comp_tracks = [t for t in target_sequence.videoTracks() if t.name() == comp_name]
    if existing_comp_tracks:
        comp_track = existing_comp_tracks[0]
    else:
        comp_track = hiero.core.VideoTrack(comp_name)
        target_sequence.addTrack(comp_track)
        print("Added VideoTrack '%s' to Sequence '%s'." % (comp_track.name(), target_sequence.name()))

    # Place the clip_or_placeholder onto comp track
    track_item = None
    try:
        if clip_obj is not None:
            track_index = list(target_sequence.videoTracks()).index(comp_track)
            target_sequence.addClip(clip_obj, 0, videoTrackIndex=track_index)
            # fetch the last added TrackItem for reporting
            added_items = [ti for ti in comp_track.items()]
            track_item = added_items[-1] if added_items else None
            print("Added workfile clip to timeline '%s' on track '%s'." % (target_sequence.name(), comp_track.name()))
        else:
            # create a placeholder TrackItem and store the workfile path in metadata if possible
            placeholder_item = comp_track.createTrackItem(os.path.basename(normalized_wf))
            # set timeline in/out to 0..0 (zero length placeholder)
            placeholder_item.setTimelineIn(0)
            placeholder_item.setTimelineOut(0)
            try:
                # Try to store the workfile path as metadata on the TrackItem so it is discoverable
                md = placeholder_item.metadata()
                if md is not None:
                    md.setValue("scriptPath", normalized_wf)
                else:
                    # older APIs: setMetadata may exist
                    if hasattr(placeholder_item, "setMetadata"):
                        placeholder_item.setMetadata("scriptPath", normalized_wf)
            except Exception:
                # best-effort: silently ignore metadata failures
                pass
            comp_track.addItem(placeholder_item)
            track_item = placeholder_item
            print("Added placeholder TrackItem for workfile to timeline '%s' on track '%s'." % (target_sequence.name(), comp_track.name()))
    except Exception as exc:
        print("Failed to add workfile to timeline: %s" % (exc,))
        raise

    return {
        "project": proj,
        "scripts_bin": scripts_bin,
        "sequence": target_sequence,
        "comp_track": comp_track,
        "track_item": track_item,
        "bin_item": created_binitem,
    }


if __name__ == "__main__":
    DEFAULT_LOCATION = r"\\192.168.150.179\share2\storage2\Projects\TVC\Sameh_20250914\footage\copy001\shots\copy001_sh0040\pl01\v001"
    plate_summary = load_plates(DEFAULT_LOCATION)

    WORKFILE = r"//aromagfx1/VFX_Projects/Projects/2024/Drama/Alf_Leila_P2/VFX_Projects/Shots/ep019/ep019_sc019/ep019_sc019_sh0170/Compositing/alf_leila_p2_ep019_sc019_sh0170_Compositing_v002.nk"
    wf_summary = load_workfile(WORKFILE, sequence=plate_summary.get("sequence"))

    print("Completed: plates and workfile loaded.")
