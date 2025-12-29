# Nuke Kitsu Loader

This package contains a dockable PySide2 panel for Nuke Studio / Hiero 12 (Python 2.7) that logs into a CGWire Kitsu instance through Gazu and imports plates plus `.nk` workfiles into synchronized `footage` and `scripts` tracks.

## Current status

The repository currently includes the Phase 1 scaffolding:

- Configurable Kitsu client wrapper in `core/kitsu_client.py`
- Utility helpers for path parsing in `core/utils.py`
- Initial PySide2 UI widgets in `ui/login_widget.py` and `ui/main_widget.py`
- Placeholder loader thread in `core/loader.py`

Further phases (sequence cards, loader expansion, tests) still need to be implemented.

## Environment validation

Phase 0 checks were executed on **2025-12-26** inside Nuke Studio 12:

| Check | Result |
| --- | --- |
| `import PySide2`, `import hiero.core`, `import gazu` | ✔️ All imports succeeded. |
| `os.path.exists(r"\\192.168.150.179\share2\storage2\Projects\TVC\Sameh_20250914\footage\copy001\shots\copy001_sh0010\pl01\v001\alf01_ep03_sc0002_sh0030_pl01_v001.1001.exr")` | ✔️ Returned `True` (`yes`). |

If a future environment deviates (missing `gazu`, inaccessible UNC path, etc.), rerun the commands above and record the new outcome before continuing development.

## Configuration options

`configs/plugin_config.json` controls runtime integration:

| Key | Description |
| --- | --- |
| `kitsu_host` | Default API root shown in the login widget. |
| `nuke_executable` | Optional absolute path to `Nuke.exe`/`NukeX.exe`. When set, the **Open Script Workfile** action launches this executable and passes the `.nk` path. Leave blank to fall back to the OS default file handler. |
| `path_mappings` | List of `{match, replace}` entries that convert repository-style paths into UNC paths reachable from the Nuke Studio host. |
| `task_type_filter` | Object with `enabled` (boolean) and `allowed_task_types` (array of strings). When enabled, only task types in the allowed list appear in sequence card task dropdowns. Use this to filter out 3D tasks (Modeling, Lighting, Animation, etc.) and show only 2D-relevant tasks (Conform, Compositing, Roto, Paint, Tracking, etc.). |

## Development quick start

1. Copy `nuke_kitsu_loader` into your Nuke/Hiero startup path (e.g. `%USERPROFILE%\.nuke`).
2. Edit `configs/plugin_config.json` to point at your Kitsu host and path mappings.
3. Launch Nuke Studio, open the *Kitsu Loader* panel, enter your credentials, and confirm that the project list populates.
4. Right-click a script-track item (or use the Timeline menu) to run **Open Script Workfile**, which launches the `.nk` stored on that item.
5. Continue implementing later phases following `guide.md`.

## Installation guide

1. Ensure `gazu` is installed in the same Python 2.7 site-packages that Nuke Studio 12 uses. If not, vendor it inside `nuke_kitsu_loader/vendor/gazu` and adjust `PYTHONPATH` accordingly.
2. Clone or copy this repository somewhere accessible to the workstation running Nuke Studio/Hiero.
3. Copy (or symlink) the `nuke_kitsu_loader` folder into your Nuke/Hiero startup directory (for example `%USERPROFILE%\.nuke\Python\Startup` on Windows).
4. Add the following line to `init.py` or `menu.py` inside the startup directory so the panel registers automatically:
	```python
	import nuke_kitsu_loader.plugin
	nuke_kitsu_loader.plugin.register_panel()
	```
5. Edit `nuke_kitsu_loader/configs/plugin_config.json` to set `kitsu_host`, `path_mappings`, and (optionally) `nuke_executable`.
6. Restart Nuke Studio/Hiero and open *Workspace → Panels → Kitsu Loader* to verify the dockable UI loads without errors.

## User guide

### Prerequisites

Before using the loader, set the following environment variables:
- **KITSU_SERVER** - Your Kitsu API URL (e.g., `https://192.168.150.179/api`)
- **KITSU_LOGIN** - Your Kitsu email/username
- **KITSU_PWD** - Your Kitsu password

### Usage Steps

1. **Login** – In the loader panel, click **Login from Environment**. The plugin will read credentials from the environment variables above. The status label will update to show the authenticated user.
2. **Select project** – Choose a project from the combobox. The plugin fetches all sequences for that project and displays them as selectable cards with per-sequence task dropdowns.
3. **Choose tasks/sequences** – For each sequence card you want to process, ensure the checkbox is enabled and pick the task whose media you want to import (e.g., `Compositing`). The loader will import both workfiles and renders from that task's comments.
4. **Run loader** – Click **Load Selected Sequences**. Progress updates and log messages appear in the lower log widget. The loader:
   - Imports **plates** from Conform task comments into the `Footage` bin
   - Imports **renders** from selected task comments into the `render` bin
   - Creates a new sequence with stacked tracks:
     - `{task}_render` track (top) - renders from selected task
     - `{task}` track (middle) - workfiles from selected task  
     - `footage` track (bottom) - plates from Conform task
5. **Comment format** – Task comments should contain both `Workfile:` and `Location:` fields:
   ```
   Workfile: \\192.168.150.179\share2\release\gizmo_10_v02.nk
   Location: \\192.168.150.179\share2\footage\A002_C018_0922BW_002.mov
   ```
6. **Open scripts** – After loading, right-click any script track item or use the Timeline menu action **Open Script Workfile** to launch the `.nk` via the configured executable.
7. **Review logs** – Successful runs produce summary messages; any errors (missing comments, unreachable paths, etc.) are logged with codes so you can address them per shot.

## Running tests

Basic parser/client tests live under `nuke_kitsu_loader/tests`. Run them from the repository root with:

```
python -m unittest discover -s nuke_kitsu_loader/tests
```
