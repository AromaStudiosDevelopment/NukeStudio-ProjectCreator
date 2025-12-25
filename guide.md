# guide.md — Nuke Studio (Hiero) PySide2 Plugin

**Goal:** produce a dockable PySide2 plugin for **Nuke Studio 12 (Python 2.7)** that connects to **CGWire Kitsu** (via **Gazu**) to: log in, let the user choose projects and sequences, fetch each selected sequence’s shots’ Conform `location` (plate path) and Workfile (`.nk`) values, import plates into a **Footage** bin and a new sequence (track `"footage"`), import Nuke scripts into a **Scripts** bin and the same sequence (track `"scripts"`) aligned to the plates.

> Audience: an AI agent (or developer agent) that will implement the plugin programmatically. The guide is written as explicit tasks, code skeletons, tests and references the key external docs.

---

## Table of contents

1. Prerequisites & environment
2. High-level architecture & data flow
3. Development milestones (epics & tasks)
4. Detailed implementation plan (per-file, functions, code snippets)
5. Kitsu (Gazu) data model & how to extract values you need
6. Hiero / Nuke Studio operations (create bin, import clip, create sequence, add tracks)
7. UI details (PySide2 cards, dockable panel, threading)
8. Error handling, edge cases & logging
9. Testing, validation & sample data
10. Deployment & installation in Nuke Studio 12 (Python 2.7)
11. Security notes & credentials handling
12. Troubleshooting / FAQs
13. References

---

## 1. Prerequisites & environment

* **Target product:** Nuke Studio / Hiero 12 (Python 2.7). Use the Hiero API (`hiero.core`, `hiero.ui`) for timeline/clip operations.
* **Kitsu client:** Gazu Python client (compatible version for your Kitsu instance). Install into the same Python environment that Nuke Studio sees (or vendor into the plugin).
* **UI toolkit:** PySide2 (available in Nuke 12). Build UI programmatically (widgets will inherit Nuke/Hiero style).
* **OS:** Windows (UNC paths in examples), ensure Nuke Studio host can reach file servers (e.g. `\\192.168...`).
* **Access:** Kitsu API URL, username & password (implement username/password login—no token-flow required initially).

**Agent responsibilities before coding**

1. Acquire a test Kitsu project (or a staging instance) and at least one project with shots that have: a Conform task comment containing `location: <UNC or path>`, and tasks with Workfile metadata (`.nk`).
2. Verify the Nuke Studio development machine has network access to sample footage paths.
3. Confirm which fields in your Kitsu instance hold the Workfile absolute path (Workfile vs. Working files). If uncertain, inspect using Gazu or raw API queries.

---

## 2. High-level architecture & data flow

1. **UI layer (PySide2):** Login widget → Project combobox → Sequence cards (sequence name, tasks combobox, checkbox) → Load button.
2. **Controller:** On login → fetch projects. On project select → fetch sequences and tasks (populate cards). On Load → collect selected sequences, send them to the loader.
3. **Loader (worker thread):** For each selected sequence:

   * Query shots → for each shot: get Conform task comment → parse `location` → import clip to Footage bin.
   * Build sequence timeline: create a new sequence, create `"footage"` and `"scripts"` tracks, create track items for plates and scripts aligned in time.
4. **Persistence & UI feedback:** progress bar, logs, and errors reported back to UI thread.

Diagram (conceptual):

```
[PySide2 UI] -> [Controller] -> [Gazu API] & [Hiero API]  -> Nuke Studio timeline + clips/bins
```

---

## 3. Development milestones (epics & tasks)

**Epic A — Setup & skeleton**

* A1: Create repo, plugin dir structure
* A2: Ensure Gazu & PySide2 importable in Nuke Studio Python 2.7
* A3: Add logging & config file (`plugin_config.json`)

**Epic B — Authentication & discover**

* B1: Implement Login widget + Gazu authentication
* B2: Fetch projects & populate Project combobox
* B3: Fetch sequences for project & tasks per sequence

**Epic C — UI: sequence cards**

* C1: Build sequence card widget with label, task combobox, checkbox
* C2: Add list container & scroll area, implement select-all

**Epic D — Loader core**

* D1: Implement shot enumeration for sequence
* D2: Implement Conform comment parser to extract `location`
* D3: Implement clip import to Footage bin (createClip or matching API)
* D4: Implement sequence creation and track population with plate track
* D5: Implement Workfile retrieval, scripts bin and script import/alignment

**Epic E — Polishing**

* E1: Progress UI & cancellation support
* E2: Error handling & user messages
* E3: Unit/integration tests and sample dataset
* E4: Packaging + installation instructions

---

## 4. Detailed implementation plan (per-file, functions, code snippets)

**Repository layout (suggested)**

```
nuke_kitsu_loader/
├─ plugin.py                # entry: register panel with Nuke/Hiero
├─ ui/
│  ├─ login_widget.py
│  ├─ main_widget.py
│  └─ sequence_card.py
├─ core/
│  ├─ kitsu_client.py       # wrapper around gazu calls
│  ├─ loader.py             # background worker to import clips/scripts
│  └─ utils.py              # parsing helpers, path utilities
├─ tests/
└─ README.md
```

### plugin.py

* Register panel as dockable widget (use Nuke or Hiero registration API depending on environment).

```python
# plugin.py (simplified)
from PySide2 import QtWidgets
# Import the UI class you'll implement
from ui.main_widget import KitsuLoaderMainWidget

def create_panel():
    return KitsuLoaderMainWidget()

# Registration code differs between Nuke and Hiero; place this file in the startup path for the host.
```

**Note:** For Nuke Studio / Hiero, place the script in the appropriate startup folder and use the host's recommended registration API.

---

### ui/login_widget.py

* Contains `QLineEdit` for API URL, username, password, and a `Login` button. On click:

  * call `kitsu_client.login(host, user, pass)` wrapper.
* On success emit `login_successful` (Qt signal) with user info.

```python
# login_widget.py (concept)
from PySide2.QtWidgets import QWidget, QLineEdit, QPushButton, QVBoxLayout

class LoginWidget(QWidget):
    def __init__(self, parent=None):
        super(LoginWidget, self).__init__(parent)
        # fields: api_url, username, password
        # bind login button -> self._do_login()
    def _do_login(self):
        # call kitsu_client.login(host, username, password)
        pass
```

---

### core/kitsu_client.py

* Provide a thin wrapper to isolate Gazu usage: `login(host, user, pass)`, `get_projects()`, `get_sequences(project)`, `get_shots(sequence)`, `get_tasks_for_sequence(sequence)`, `get_latest_task_comment(task_name, shot)`, `get_workfile_for_shot(task, shot)`, and `raw_request()` fallback if needed.

Key functions (pseudo):

```python
def login(host, username, password):
    # configure client host and log in
    pass

def get_projects():
    # return list of projects
    pass
```

**Important:** Kitsu instances vary; confirm where Workfile paths are stored and implement fallbacks using raw API queries if necessary.

---

### core/utils.py — Conform comment parser

* Conform comments typically include a line like `location: \\server\path\...` — implement a robust parser:

  * Accept tokens `location:`, `Location:`, `path:`
  * Extract UNC or local path including spaces
  * Validate that path exists (optional: `os.path.exists` from the host where Nuke runs)
  * If the comment contains multiple locations, pick the one that points to a valid media file or folder.

Example parser:

```python
import re

def extract_location_from_comment(comment_text):
    m = re.search(r'location\s*:\s*(.+)', comment_text, re.I)
    if m:
        p = m.group(1).strip()
        p = p.rstrip(' .;')
        return p
    return None
```

---

### core/loader.py — worker responsibilities

**Goal:** perform all heavy operations off the UI thread. Use `QThread` or `QRunnable` (PySide2) to avoid blocking the UI.

Steps for each selected sequence:

1. `shots = kitsu_client.get_shots(sequence)`
2. For each shot:

   * `conform_comment = kitsu_client.get_latest_task_comment(shot, "Conform")`
   * `location = utils.extract_location_from_comment(conform_comment)`
   * Validate `location` points to media (file / image sequence)
   * `clip = create_clip_in_footage_bin(location)` → using Hiero API
   * Keep ordered list `[(shot_name, clip, script_path_or_None), ...]`
3. Create new `Sequence` in project
4. Create `footage` track and push track items for each clip preserving shot order
5. For each shot, attempt to fetch Workfile and import into `Scripts` bin and `scripts` track aligned to the clip duration

**Important Hiero API calls:** Use `project.clipsBin()` or `hiero.core.Bin` and `bin.createClip(path)` to import media.

---

## 5. Kitsu (Gazu) data model & extraction tips

* **Hierarchy:** Projects → Sequences → Shots → Tasks → Comments / Working files.
* **Conform location:** many studios put the plate path in the latest comment on the Conform task. Implement comment scanning and `location:` extraction.
* **Workfile (`.nk`):** may be stored as a Working File or an uploaded file on the task. Implement logic to find the latest `.nk` in working files; if absent, provide fallback behavior.

**Fallback strategy:**

1. Try high-level helper to get the main working file for the chosen task.
2. If not present, list working files and pick the latest `.nk` by name or type.
3. If still not found, log and continue (import plates only).

---

## 6. Hiero / Nuke Studio operations (create bin, import clip, create sequence, add tracks)

**Essential operations (pseudo-code):**

* **Create / find bin**

```python
project_bin = project.clipsBin()
footage_bin = hiero.core.Bin("Footage")
project_bin.addItem(footage_bin)
```

* **Import clip**

```python
clip = footage_bin.createClip(path_to_media)
```

* **Create sequence**

```python
sequence = hiero.core.Sequence(sequence_name)
bin_item = hiero.core.BinItem(sequence)
project_bin.addItem(bin_item)
```

* **Add video tracks**

```python
from hiero.core import VideoTrack
footage_track = VideoTrack("footage")
sequence.addTrack(footage_track)
scripts_track = VideoTrack("scripts")
sequence.addTrack(scripts_track)
```

* **Create track items aligned to clip**

```python
track_item = footage_track.createTrackItem(clip.name())
track_item.setSource(clip)
footage_track.addItem(track_item)
```

**Notes:** If Nuke Studio does not accept `.nk` files as timeline clips, implement a proxy strategy (attach `.nk` as metadata and/or create a small preview clip to represent the script on the timeline).

---

## 7. UI details (PySide2 cards, dockable panel, threading)

**Sequence card widget**

* Horizontal layout with:

  * `QLabel`: sequence name
  * `QComboBox`: tasks for sequence
  * `QCheckBox`: include
* Provide right-click context menu: "Select all shots", "Expand/Collapse".

**Dockable registration**

* Use the host's recommended API to register a dockable PySide widget. Place `plugin.py` in the correct startup path.

**Threading**

* Use `QThread` or `QThreadPool` to run loader operations asynchronously. Communicate progress via Qt signals and support cancellation by checking a cancel flag in the worker.

---

## 8. Error handling, edge cases & logging

* **Missing Conform comment** → log & show warning for that shot, continue to next shot.
* **Invalid/missing Workfile** → import plates only and log details.
* **Network path not reachable** → detect with `os.path.exists` (runs on Nuke host). If unreachable, attempt to map or prompt user.
* **Script import limitations** → if `.nk` cannot be imported, attach path as metadata and provide an "Open script" action to launch Nuke with that script.

**Logging:** write to both the host log and an on-disk rolling log for debugging (e.g. `logs/kitsu_loader.log`). Include timestamps and severity.

---

## 9. Testing, validation & sample data

**Unit tests:**

* `utils.extract_location_from_comment()` with varied comment formats.
* `kitsu_client` wrappers with mocked responses.

**Integration tests (manual):**

* Use a Kitsu staging project with: Conform comments and Workfiles present. Validate that:

  * Clips appear in `Footage` bin.
  * Sequence created and `footage` track contains clips in the correct order.
  * `scripts` track contains script proxies aligned with plates.

**Acceptance criteria:**

* With at least one selected sequence, the plugin creates a sequence with two tracks (`footage` & `scripts`), imports clips, aligns items, and produces no unhandled exceptions.

---

## 10. Deployment & installation in Nuke Studio 12 (Python 2.7)

1. Place plugin folder under the host startup path (e.g. `~/.nuke/` or Hiero startup path).
2. Ensure `gazu` is available to Nuke’s Python runtime: either vendor the package or install it into the same Python environment used by Nuke.
3. Add a startup script (`plugin.py`) that registers the panel/menu and initializes the plugin.
4. Restart Nuke Studio and confirm the panel appears.

---

## 11. Security notes & credentials handling

* **Do not hardcode credentials.** Keep them in memory only at runtime.
* Optionally, support secure local storage (OS credential manager) if persistent login is required.
* Prefer `https` endpoints for Kitsu and validate certificates when possible.

---

## 12. Troubleshooting / FAQs

**Q: Conform comment contains multiple location lines or file list.**

* A: Choose the last (most recent) `location:` or the one that points to an existing path. Provide UI override if needed.

**Q: NK scripts do not import into Nuke Studio timeline.**

* A: Implement a proxy strategy: import a preview clip and attach `.nk` as metadata, or provide an "Open script" direct action.

**Q: UI hangs during long import.**

* A: Ensure all import operations run in a background `QThread` and report progress via Qt signals.

---

## 13. References

* Gazu (Kitsu Python client) documentation and examples.
* Foundry Hiero / Nuke Studio Python developer guides and `hiero.core` examples.
* Foundry documentation and community examples for creating dockable PySide widgets in Nuke/Hiero.

---

## Appendix — Helpful code snippets (adapted for Python 2.7 / PySide2)

**QThread skeleton (PySide2 / Python 2.7):**

```python
from PySide2.QtCore import QThread, Signal

class LoaderThread(QThread):
    progress = Signal(int)
    message = Signal(str)
    finished = Signal()

    def __init__(self, tasks, parent=None):
        super(LoaderThread, self).__init__(parent)
        self.tasks = tasks
        self._cancel = False

    def run(self):
        for i, t in enumerate(self.tasks):
            if self._cancel:
                break
            self.message.emit("Processing %s" % t.name)
            # perform import steps ...
            self.progress.emit(int((i+1)/float(len(self.tasks))*100))
        self.finished.emit()

    def cancel(self):
        self._cancel = True
```

**Conform comment parser example**

```python
import re

def extract_location(comment_text):
    if not comment_text:
        return None
    m = re.search(r'location\s*:\s*([\\\\A-Za-z0-9_:/.\-\\ ]+)', comment_text, re.I)
    return m.group(1).strip() if m else None
```

---

## Next actions for the AI agent (immediate checklist)

1. **Validate environment**: confirm `gazu` importability from Nuke Studio Python 2.7; if not, vendor `gazu` package.
2. **Create small prototype**: implement minimal login UI and list projects.
3. **Create a Hiero smoke test**: from Nuke Studio Python REPL, run a small `create_example` snippet to create a dummy sequence and verify in UI.
4. **Implement parser & loader skeleton**: test parsing of real Conform comments and test importing a single clip into a `Footage` bin.
5. **Iterate**: add script import logic and alignment, polish UI, add progress & logging.

---

## Final notes / assumptions & caveats

* **Assumption:** Conform `location` follows `location: <path>` convention in comments. If studio workflow differs, the agent must inspect sample comments and adapt the parser.
* **Caveat:** Importing `.nk` files into Nuke Studio timeline can be environment-specific. If direct import isn't supported, implement a proxy workflow (thumbnail or metadata attachment) and test early.

---

*End of document.*
