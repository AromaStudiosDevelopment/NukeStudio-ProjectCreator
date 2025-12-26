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

## Development quick start

1. Copy `nuke_kitsu_loader` into your Nuke/Hiero startup path (e.g. `%USERPROFILE%\.nuke`).
2. Edit `configs/plugin_config.json` to point at your Kitsu host and path mappings.
3. Launch Nuke Studio, open the *Kitsu Loader* panel, enter your credentials, and confirm that the project list populates.
4. Right-click a script-track item (or use the Timeline menu) to run **Open Script Workfile**, which launches the `.nk` stored on that item.
5. Continue implementing later phases following `guide.md`.

## Running tests

Basic parser/client tests live under `nuke_kitsu_loader/tests`. Run them from the repository root with:

```
python -m unittest discover -s nuke_kitsu_loader/tests
```
