# Deep Guide for an AI Agent: Generate a Python Tool to Produce `.hrox` (hieroXML) Projects

**Purpose:**
This guide instructs an autonomous AI agent how to design, implement, test, and deliver a production-ready Python tool that programmatically generates Hiero / Nuke Studio read-only project exports (`.hrox`, a `hieroXML` manifest). The document is written so the agent can operate with minimal human supervision and provides step-by-step technical tasks, validation checks, error handling, and a final delivery checklist.

---

## 0 — High-level overview (goal)

Produce a Python package (`hrox-generator`) that:

* Accepts a structured input (JSON/CSV) describing a timeline: media file list, optional Nuke script references, track assignments, timeline positions, and project settings.
* Computes or validates media durations (frame counts) using `ffprobe` when necessary.
* Builds a conformant `hieroXML` (`.hrox`) file containing `Media`, `Project`, `trackItemCollection`, and `Sequence` elements with correct GUIDs and attributes.
* Writes a syntactically valid file including `<?xml ...?>` and `<!DOCTYPE hieroXML>` header and is loadable by Hiero/Nuke Studio.

Deliverables:

* Python source package with CLI and library API.
* Unit tests for the key generation functions.
* Example input files and generated `.hrox` sample(s).
* README and an automated smoke test that opens the produced `.hrox` in a local test environment (manual verification instruction if Hiero/Nuke Studio is not installed).

---

## 1 — Capabilities & environment requirements for the agent

Agent must:

* Run Python 3.9+.
* Have `ffprobe` available on PATH (or use a configurable fallback mode).
* Be able to read local filesystem paths.
* Install and use Python libraries: `lxml` (preferred) or fallback to `xml.etree.ElementTree`.
* Use `uuid` for GUID generation.
* Use subprocess execution (`subprocess`) to call `ffprobe` safely.

Security rules:

* Sanitize file paths and validate file existence before using them.
* Avoid executing untrusted code; passed Nuke `.nk` file paths are treated as opaque media references only.

---

## 2 — Input schema (JSON canonical model)

Provide a single canonical JSON schema the agent will accept. Example:

```json
{
  "project": {
    "name": "GeneratedProject",
    "framerate": "25/1",
    "samplerate": "48000/1",
    "timecodeStart": 90000,
    "viewerLut": "ACES/Rec.709",
    "ocioConfigName": "aces_1.2"
  },
  "tracks": [
    {"name": "Video 1", "kind": "video"},
    {"name": "VFX 1", "kind": "video"},
    {"name": "Audio 1", "kind": "audio"}
  ],
  "clips": [
    {"file": "D:/path/clipA.mov", "track": "Video 1", "timelineIn": 0},
    {"file": "D:/path/clipB.mov", "track": "Video 1", "timelineIn": 100}
  ]
}
```

Agent must validate this schema and report missing/invalid fields.

---

## 3 — Core implementation tasks (step-by-step)

### 3.1 Project bootstrap

* Create a Python package skeleton: `hrox_generator/`, `hrox_generator/__init__.py`, `cli.py`, `generator.py`, `schema.py`, `tests/`, `examples/`.
* Add `pyproject.toml` or `setup.cfg` for packaging and dependencies (`lxml` optional).

### 3.2 Input parsing & validation

* Implement a `schema.py` that validates input JSON via either a small custom validator or `jsonschema`.
* Normalize framerate (e.g., accept `25` or `25/1`) into numerator/denominator integers.
* Normalize paths (resolve symlinks, expanduser); ensure files exist.

### 3.3 Media metadata extraction

* Implement `get_framecount(path)`:
  * Primary method: call `ffprobe -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 <file>` and parse the integer.
  * Fallback: `ffprobe``duration` and `avg_frame_rate` to estimate frames (round to nearest int).
  * If `ffprobe` fails and the user provided `sourceDuration` in the input, use that.
  * Log warnings for estimated vs counted values.
* Return integer framecounts or `None` if unavailable.

### 3.4 GUID management

* Implement `gen_guid()` using `uuid.uuid4()` and format with braces: `{xxxxxxxx-xxxx-...}`.
* Build mapping dictionaries for `source_path -> source_guid` and `clip_id -> trackitem_guid`.

### 3.5 XML model construction

* Use `lxml.etree` (preferred): it supports DOCTYPE, pretty printing, and namespaces.
* Minimal required XML nodes:
  * Root: `<hieroXML name="NukeStudio" version="11" release="12.2v2">` (set `version`/`release` to the target app version).
  * `<Media>` with `<Source file="..." name="..." guid="{...}" duration="..."/>` for each media.
  * `<Project ...>` with attributes from input.
  * `<trackItemCollection>` with `<TrackItem ...>` for each clip, including nested `<MediaGroup>` -> `<groupdata>` -> `<MediaInstance_Vector>` -> `<Source guid="{...}"/>` links.
  * `<Sequence>` -> `<videotracks>` -> multiple `<VideoTrack>` elements -> `<trackItems>` referencing TrackItem GUIDs.

### 3.6 DOCTYPE and file write

* Use `lxml.etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8', doctype='<!DOCTYPE hieroXML>')` to produce the header + DOCTYPE in a single pass.
* If `lxml` is not available, use `xml.etree.ElementTree` to produce the XML body, then write header + DOCTYPE manually before the body (see tests and examples).

### 3.7 CLI and API

* `cli.py` should accept:
  * `--input <json>`
  * `--output <file.hrox>`
  * `--ffprobe-path <path>` optional
  * `--use-relative-paths` flag
  * `--dry-run` modes
* Expose a library function `generator.generate_hrox(input_object, out_path, options)`.

---

## 4 — Edge cases, validations, and robustness

* **Missing files:** Create placeholder `Source` entries but mark their file attribute as `MISSING:<path>` and warn. Do not crash unless `--strict` is set.
* **Frame mismatch:** If a clip's `sourceDuration` is shorter than the timeline slot, produce a `WARNING` and optionally clip the timelineDuration.
* **Path portability:** Provide `--path-base` option to convert absolute paths to relative ones by substituting a root path.
* **Version compatibility:** Expose `--target-release` parameter so generated `release` attribute can match the target Hiero/Nuke Studio release.

---

## 5 — Testing & QA plan

### Unit tests

* Test GUID format generator: ensure unique & braced.
* Test ffprobe wrapper: use small test video files (or mocked subprocess) to return expected framecounts.
* Test XML generation: feed a minimal JSON and compare generated XML tree structure (parse back with `lxml` and assert expected elements and attributes).

### Integration tests

* Produce a `.hrox` from `examples/example_project.json` and include the sample media (or symlink placeholders). Attempt to open the file in a local Hiero/Nuke Studio installation (manual) and confirm:
  * Tracks exist with expected names.
  * Clips map to correct media by path.
  * Timecode and framerate are correct.

### Smoke tests for DOCTYPE handling

* Test both `lxml` and the manual `ElementTree + manual doctype` flows to ensure both output a well-formed `.hrox` that Hiero accepts.

---

## 6 — Logging, observability, and error reporting

* Use `logging` with levels: DEBUG / INFO / WARNING / ERROR.
* Create a JSON `--report <file.json>` option that writes a manifest of actions, chosen frame counts, and any warnings (useful for later debugging).

---

## 7 — Example prompts for the AI agent (to create code & tests)

Use the following prompts as tasks assigned to the agent sequentially.

### Prompt A — Implement ffprobe wrapper

> Implement a function `get_framecount(path: str, ffprobe_path: Optional[str]=None) -> Optional[int]`. Use `subprocess` to call `ffprobe -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nokey=1:noprint_wrappers=1 <path>`. Parse output and return integer. If ffprobe fails, fall back to using `duration` and `avg_frame_rate`. Write unit tests mocking subprocess.

### Prompt B — Build XML skeleton

> Implement `build_hiero_tree(input_obj: dict) -> lxml.etree._ElementTree` that returns an `lxml` ElementTree for the full `hieroXML` structure described in this guide. The function must not write to disk. Create unit tests that assert presence of `Media`, `Project`, `trackItemCollection`, and `Sequence` nodes.

### Prompt C — Write file safely

> Implement `write_hrox(tree, outpath)` that writes the tree to disk with `<!DOCTYPE hieroXML>` using `lxml`. Provide fallback logic if `lxml` is not installed (write header manually + ElementTree serialization).

### Prompt D — CLI & packaging

> Create `cli.py` and `pyproject.toml` that expose the package as a console script `hroxgen`. Add documentation in README describing usage.

---

## 8 — Example minimal test case (JSON input)

```json
{
  "project": {
    "name": "GeneratedProject",
    "framerate": "25/1",
    "samplerate": "48000/1",
    "timecodeStart": 90000
  },
  "tracks": [ {"name": "Video 1", "kind":"video"} ],
  "clips": [ {"file": "examples/media/clipA.mov", "track": "Video 1"} ]
}
```

Expected results:

* A file `GeneratedProject.hrox` containing one `Source` for `clipA.mov` and one `TrackItem` referencing it, placed at `timelineIn = 0`.

---

## 9 — Deliverable checklist for final verification

* [ ]  `hroxgen` CLI that consumes JSON and produces `.hrox`.
* [ ]  `generator.generate_hrox()` library API with documented parameters.
* [ ]  Unit tests covering GUID creation, ffprobe wrapper, XML generation.
* [ ]  Example inputs and generated `.hrox` files checked manually in Hiero/Nuke Studio.
* [ ]  README.md with instructions, usage examples, and troubleshooting.
* [ ]  JSON report output of last run containing warnings and metadata.

---

## 10 — Handoff and maintenance notes

* Keep the `--target-release` value explicit; if Hiero/Nuke Studio updates change XML structure or required attributes, update templates in `templates/` and add regression tests.
* If the studio uses a custom OCIO / Look system, populate `Project` viewerLut and `ocioConfigName` from configuration templates.
* Document known limitations (e.g., this tool does not validate Nuke script internals; it treats them as referenced assets only).

---

*End of guide.*
