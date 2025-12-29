# copilot-instructions.md — Nuke Studio Kitsu Loader (Agent Instructions)

## Purpose

This document contains **precise, step‑by‑step instructions** for an AI developer agent (Copilot-style) to implement a dockable PySide2 plugin for **Nuke Studio 12 / Hiero (Python 2.7)** that integrates with a CGWire Kitsu instance (via Gazu). The plugin must enable a user to log in, select a project and sequences, and import shot plates and Nuke scripts into a new Nuke Studio sequence with a `footage` track and a `scripts` track aligned to the plates.

This file assumes you have access to a Kitsu instance, a Nuke Studio 12 installation with network access to media shares, and the authority to install Python packages into the host environment (or vendor them into the plugin).

---

## Agent operating rules (how you must behave)

* Target runtime: **Python 2.7** and **PySide2** inside Nuke Studio 12. All Python code must be compatible with Python 2.7 syntax. Use `unicode`/`str` care where applicable.
* Use **Gazu** for Kitsu interactions. Wrap all Gazu usage behind `core/kitsu_client.py` to isolate network calls and simplify unit testing/mocking.
* Use **hiero.core** and Hiero APIs for clip/sequence operations. Abstract Hiero calls behind a small wrapper layer if helpful for testability.
* Run all heavy I/O and network operations in a background worker (`QThread` or `QRunnable`) and communicate status with Qt signals. The main UI thread must never block for long operations.
* Be explicit in error handling. Any operation that can fail (network call, path not found, createClip failure) must return structured error messages and not raise unhandled exceptions.
* Provide clear, machine-readable logs (JSON lines or structured logs) and human-readable UI messages.
* Implement incremental behavior: produce a prototype that logs and imports a single shot before adding batch processing, progress, and script import features.

---

## Quick summary of features to implement

1. Dockable PySide2 panel inside Nuke Studio 12 with:

   * Login area (API URL, username, password)
   * Project combobox
   * Scrollable list of **sequence cards**, each card shows: sequence name, task combobox, include checkbox
   * Load button that triggers the loader
2. On Load, for each selected sequence:

   * Fetch shots
   * For each shot, retrieve the latest **Conform** task comment, parse `location:` to obtain the plate path
   * Import plate (clip or image sequence) into a `Footage` bin and create a clip
   * Create a new Sequence named after the Kitsu sequence and add a video track named `footage` containing all clips in order
   * For the task chosen in the sequence card (e.g. `Compositing`), fetch the shot’s Workfile (`.nk`), import or proxy it into a `Scripts` bin and place aligned track items in a `scripts` track
3. Support progress updates, cancelation, and robust logging

---

## Repository structure (create these files)

```
nuke_kitsu_loader/
├─ plugin.py
├─ README.md
├─ ui/
│  ├─ __init__.py
│  ├─ login_widget.py
│  ├─ main_widget.py
│  └─ sequence_card.py
├─ core/
│  ├─ __init__.py
│  ├─ kitsu_client.py
│  ├─ loader.py
│  └─ utils.py
├─ tests/
└─ configs/
   └─ plugin_config.json
```

Implement code in these files. Keep functions small and well-documented. Use docstrings for every public function.

---

## Detailed tasks for the agent (ordered, atomic)

### Phase 0 — Environment validation (Required first)

* Task 0.1: From inside Nuke Studio Python console, run `import PySide2; import hiero.core; import gazu`. Capture and report import errors. If `gazu` is missing, vendor the `gazu` package into `nuke_kitsu_loader/vendor/gazu/`.
* Task 0.2: Confirm access to the file shares referenced in sample Conform comments (run `os.path.exists(r"\\\\server\path\file.mov")` from Nuke Python). Report permission or mount issues.

**Acceptance:** All required modules import successfully or a vendor fallback exists. Media paths are reachable or agent reports exact failure details.

---

### Phase 1 — Minimal prototype (login + project list)

* Task 1.1: Implement `core/kitsu_client.py` with functions:

  * `login(host, username, password)` — sets host and authenticates; returns (True, user_info) or (False, error_msg)
  * `get_projects()` — returns a list of project dicts `{id, name, data}`
  * `get_sequences(project_id)` — returns sequences for a project
  * `get_tasks_for_sequence(sequence_id)` — returns tasks list

  Keep responses simple Python lists/dicts for easy consumption by UI.

* Task 1.2: Implement `ui/login_widget.py` with a small PySide2 form and a `login_successful` Qt signal. On login success emit the signal with a minimal context object (host, username).

* Task 1.3: Implement `ui/main_widget.py` skeleton: listens to `login_successful`, calls `kitsu_client.get_projects()`, fills project combobox.

**Acceptance:** From the panel, after entering credentials, projects load into the combobox with no unhandled exceptions.

---

### Phase 2 — Sequence cards and task population

* Task 2.1: Implement `ui/sequence_card.py` — a QWidget with `QLabel` (sequence name), `QComboBox` (tasks), `QCheckBox` (include). Provide methods: `set_tasks(tasks)`, `is_selected()`.
* Task 2.2: In `main_widget.py`, when a project is selected, call `get_sequences(project_id)` and instantiate a `sequence_card` for each sequence. Populate each card’s task combobox by calling `get_tasks_for_sequence(sequence_id)`.

**Acceptance:** Project selection populates a scrollable list of sequence cards with tasks in each combobox.

---

### Phase 3 — Conform comment parsing & plate import (single sequence run)

* Task 3.1: Implement `core/utils.py` with `extract_location_from_comment(text)`:

  * Use robust regex to match `location:` (case-insensitive)
  * Accept UNC (`\\\\host\share\...`), absolute `/` paths, or studio repository-style paths
  * Trim trailing punctuation and whitespace
  * Return `None` when no viable path found

* Task 3.2: Implement `core/loader.py` with a `LoaderThread(QThread)` class that accepts a list of sequence IDs (and selected task names). Implement `run()` to process **only the first sequence and first shot** as a smoke test:

  * Get shots for the sequence
  * For the first shot: get Conform task comments, parse location, call `import_clip_to_footage_bin(path)` (Hiero operation)
  * Report progress and message signals to UI

* Task 3.3: Implement `import_clip_to_footage_bin(path)` using Hiero API (`project.clipsBin().createClip(path)` or equivalent). If `createClip` fails, return a structured error.

**Acceptance:** With one sequence selected and Load pressed, the plugin imports the first plate successfully and updates UI with progress; no UI blocking.

---

### Phase 4 — Full sequence import & sequence construction

* Task 4.1: Extend `LoaderThread.run()` to iterate all shots in a sequence, in shot order. For each shot:

  * Parse Conform location
  * Validate media exists (`os.path.exists`) **on Nuke host**; if image sequence use pattern detection (`%04d` or similar) or allow Hiero to probe
  * Create or reuse a `Footage` bin and import the clip
  * Record `[(shot_name, clip, clip_duration, script_path_or_None), ...]`
* Task 4.2: Create a new `hiero.core.Sequence(sequence_name)` and add a `VideoTrack` named `footage`. For each imported clip create a `TrackItem`, set its source to the clip, and set timeline in/out appropriately so clips appear sequentially in the track.
* Task 4.3: Add robust progress reporting every shot, and a cancelation flag checked between shots.

**Acceptance:** After processing a sequence, the project contains a new sequence named correctly, with a layer/track `footage` containing all shot clips in order.

---

### Phase 5 — Workfile retrieval and scripts track

* Task 5.1: In `kitsu_client.py` implement `get_latest_workfile_for_shot(shot_id, task_name)`:

  * Prefer high-level `gazu.files` helpers for working files
  * If high-level helpers fail, query task uploads/working-files, filter for `.nk` extensions, select the latest by timestamp
  * Return a path that’s usable on the Nuke host (translate repo path to UNC if studio requires a mapping; expose translation hook).
* Task 5.2: Extend the loader to create a `Scripts` bin and a `scripts` track in the same sequence. For each shot, if a workfile exists:

  * If Hiero supports importing `.nk` as a clip, import it directly and create track item; otherwise create a small proxy clip (e.g., a 1‑frame still or thumbnail) and attach `.nk` path as metadata to the proxy track item. Provide a context-menu action `Open Script` that launches Nuke and opens the `.nk` file.
* Task 5.3: Align `scripts` track items to the exact timeline positions of their corresponding `footage` track items.

**Acceptance:** Scripts are visible in `Scripts` bin, `scripts` track items are aligned to their plates, and user can open `.nk` from the context menu.

---

### Phase 6 — Polishing: UI/UX, logging, tests, packaging

* Task 6.1: Add a progress bar and a log panel (text widget) in `main_widget` to show live messages and error counts.
* Task 6.2: Add visual state (disabled controls) while loader runs; allow cancelation.
* Task 6.3: Add unit tests for `utils.extract_location_from_comment` and `kitsu_client` with mocked responses. Add an integration test script that runs the loader on a small sample project and verifies expected sequence and bin creation.
* Task 6.4: Build installation instructions: vendor `gazu` if needed, place plugin folder in Nuke/Hiero startup path, and add a small bootstrap `plugin.py` that registers UI.

**Acceptance:** The plugin has basic test coverage and clear installation instructions. A QA test run succeeds on sample data.

---

## File-level implementation guides (snippets & constraints)

### plugin.py

* Responsibilities:

  * Register the dockable panel with Nuke Studio/Hiero on startup
  * Ensure PySide2 import and UI creation runs under the host
* Deliver:

  * `register_panel()` function that the startup script calls

### ui/login_widget.py

* Signals:

  * `login_successful(host, username)`
  * `login_failed(error_msg)`
* Behavior:

  * Disable login button while authenticating
  * Provide readable error text on failures

### ui/main_widget.py

* Composition:

  * Top: Login state and selected project
  * Middle: Scroll area of sequence cards
  * Bottom: Load button, progress bar, message log
* Behavior:

  * On Load: collect selected sequences with chosen task names, instantiate `LoaderThread` and start
  * Connect loader signals to UI update functions

### core/kitsu_client.py

* Implementation notes:

  * Wrap all external calls in try/except and return `(ok, payload_or_error)` tuples
  * Normalize objects to plain dicts before returning to UI (avoid returning Gazu objects to UI)
  * Provide a `translate_repo_path_to_unc(repo_path)` hook function (configurable mapping in `configs/plugin_config.json`)

### core/loader.py

* Implement `LoaderThread(QThread)` with signals: `progress(int)`, `message(str)`, `complete(dict_summary)`, `error(dict)`
* Process steps: fetch shots → gather plate path → import clip → optional script retrieval → build in-memory timeline plan → create Hiero Sequence and tracks → commit track items
* Ensure filesystem checks run on Nuke host and fail gracefully when missing files

### core/utils.py

* Provide:

  * `extract_location_from_comment(text)`
  * `is_image_sequence(path)` — returns `(is_seq, frame_pattern)`
  * `normalize_path(path, mapping_config)` — map repo paths to UNC

---

## Error handling and telemetry

* All background operations must capture exceptions and send structured errors via `error()` signal. Each error object: `{code: 'MISSING_FILE'|'KITSU_ERROR'|'HIER O_ERROR'|'IMPORT_FAIL', message: str, shot: shot_name, details: {}}`.
* Keep a rolling in-memory summary and write a final JSON summary file to `~/kitsu_loader_runs/<timestamp>.json` containing processed sequences, counts, and failures.

---

## Acceptance tests (automatable scenarios)

1. **Smoke test:** valid credentials → projects list populates → select a project with 1 sequence and 1 shot with valid Conform location → Load → new sequence created, `Footage` bin contains imported clip.
2. **Script proxy test:** a shot with a `.nk` Workfile but Nuke Studio cannot import `.nk` as a clip → loader creates proxy clip and `Open Script` launches Nuke with the `.nk` path.
3. **Missing Conform location:** a shot with missing Conform comment → loader continues and logs the missing shot; summary flags a `MISSING_LOCATION` error.
4. **Network path permission failure:** `os.path.exists` false on a plate path → loader logs `UNREACHABLE_PATH` and proceeds with next shot.

Each test should assert expected bins, sequences, track names, and error summary entries.

---

## Deployment checklist (final)

* [ ] Vendor or install `gazu` accessible to Nuke Studio Python 2.7
* [ ] Place `nuke_kitsu_loader` in Nuke/Hiero startup path
* [ ] Add `plugin.py` to register the panel and menu
* [ ] Provide `configs/plugin_config.json` with host/mapping sample
* [ ] Document how to enable verbose logging and where to find run summaries

---

## Final notes & assumptions (explicit)

* **Assume** Conform `location:` convention exists in comments. If not, the agent must be instructed to inspect sample comments and adapt parsing rules.
* **Assume** Workfile `.nk` references are discoverable via working files or task uploads. If not, add an explicit studio mapping step.
* **Important:** importing `.nk` into the Hiero timeline is environment-dependent. If direct import is not supported, implement the two-step proxy + `Open Script` flow.

---

## Next immediate actions for the agent (in priority order)

1. Run environment checks (Phase 0).
2. Implement Phase 1 to produce a working Login → Projects UI.
3. Deliver a short report showing console outputs of `import hiero.core` and `import gazu` along with any exceptions.
4. After Phase 1 passes, continue to Phase 2.

---

*End of copilot-instructions.md*
