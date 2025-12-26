# -*- coding: utf-8 -*-
"""UI actions such as context menus and global shortcuts."""

from __future__ import absolute_import

import json
import logging
import os
import subprocess
import sys

from PySide2 import QtWidgets  # pylint: disable=import-error

try:
    import hiero.core  # pylint: disable=import-error
    import hiero.ui  # pylint: disable=import-error
    from hiero.core import events as hiero_events  # pylint: disable=import-error
except ImportError:  # pragma: no cover - only available inside Nuke Studio
    hiero = None
    hiero_events = None

LOGGER = logging.getLogger(__name__)
_CONFIG_CACHE = None
_CONTEXT_HELPER = None
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'configs', 'plugin_config.json')


def _load_config():
    """Load shared configuration for launcher features."""
    global _CONFIG_CACHE  # pylint: disable=global-statement
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if not os.path.exists(_CONFIG_PATH):
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    try:
        with open(_CONFIG_PATH, 'r') as handle:
            _CONFIG_CACHE = json.load(handle)
    except Exception as exc:  # pragma: no cover - config errors
        LOGGER.warning('Failed to load config %s: %s', _CONFIG_PATH, exc)
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def register_actions():
    """Register custom actions and context-menu hooks."""
    global _CONTEXT_HELPER  # pylint: disable=global-statement
    if hiero is None:
        return
    if _CONTEXT_HELPER is None:
        _CONTEXT_HELPER = _ScriptContextHelper()


class _ScriptContextHelper(object):
    """Installs the Open Script action into menus and context menus."""

    def __init__(self):
        self._action = QtWidgets.QAction('Open Script Workfile', None)
        self._action.triggered.connect(self._open_selected_script)
        try:
            hiero.ui.registerAction(self._action)
        except Exception:  # pragma: no cover - defensive
            LOGGER.debug('registerAction unavailable')
        for menu_path in ('Timeline', 'foundry.menu.timeline'):
            try:
                hiero.ui.addMenuAction(menu_path, self._action)
            except Exception:
                continue
        if hiero_events is not None:
            for event_name in ('kShowContextMenu/kTimeline', 'kShowContextMenu/kSpreadsheet'):
                try:
                    hiero_events.registerInterest(event_name, self._context_menu_handler)
                except Exception:
                    LOGGER.debug('Could not register context menu interest %s', event_name)

    def _context_menu_handler(self, event):
        menu = getattr(event, 'menu', None)
        if menu is None:
            return
        action = menu.addAction('Open Script Workfile')
        action.triggered.connect(self._open_selected_script)

    def _open_selected_script(self):
        track_items = self._selected_track_items()
        for item in track_items:
            script_path = self._script_path_from_item(item)
            if script_path:
                self._launch_script(script_path)
                return
        self._show_message('No script metadata found on the current selection.', is_error=True)

    def _selected_track_items(self):
        items = []
        try:
            sequence = hiero.ui.activeSequence()
        except Exception:
            sequence = None
        if sequence:
            timeline = hiero.ui.getTimelineEditor(sequence)
            if timeline is not None:
                try:
                    selection = timeline.selection()
                except Exception:
                    selection = []
                items.extend([entry for entry in selection if isinstance(entry, hiero.core.TrackItem)])
        if items:
            return items
        selection_manager = getattr(hiero.ui, 'selectionManager', None)
        if callable(selection_manager):
            try:
                manager = selection_manager()
                selection = manager.selection()
            except Exception:
                selection = []
            for entry in selection:
                if isinstance(entry, hiero.core.TrackItem):
                    items.append(entry)
                elif hasattr(entry, 'activeItem'):
                    try:
                        active = entry.activeItem()
                    except Exception:
                        active = None
                    if isinstance(active, hiero.core.TrackItem):
                        items.append(active)
        return items

    def _script_path_from_item(self, track_item):
        candidates = []
        try:
            metadata = track_item.metadata()
        except Exception:
            metadata = None
        if metadata is not None:
            candidates.append(metadata)
        try:
            tags = track_item.tags()
        except Exception:
            tags = []
        for tag in tags or []:
            try:
                candidates.append(tag.metadata())
            except Exception:
                continue
        for container in candidates:
            if container is None:
                continue
            for key in ('kitsu.script_path', 'script_path', 'scriptPath'):
                try:
                    value = container.value(key)
                except Exception:
                    value = None
                if value:
                    return value
        return None

    def _launch_script(self, script_path):
        if not os.path.exists(script_path):
            self._show_message('Script path does not exist: %s' % script_path, is_error=True)
            return
        config = _load_config()
        command = config.get('nuke_executable') or None
        try:
            if command:
                subprocess.Popen([command, script_path])  # pylint: disable=consider-using-with
            elif sys.platform.startswith('win'):
                os.startfile(script_path)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', script_path])  # pylint: disable=consider-using-with
            else:
                subprocess.Popen(['xdg-open', script_path])  # pylint: disable=consider-using-with
        except Exception as exc:
            LOGGER.error('Failed to launch script %s: %s', script_path, exc)
            self._show_message('Failed to launch script: %s' % exc, is_error=True)

    def _show_message(self, text, is_error=False):
        parent = hiero.ui.mainWindow() if hasattr(hiero.ui, 'mainWindow') else None
        icon = QtWidgets.QMessageBox.Critical if is_error else QtWidgets.QMessageBox.Information
        box = QtWidgets.QMessageBox(parent)
        box.setIcon(icon)
        box.setWindowTitle('Kitsu Loader')
        box.setText(text)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.show()
*** End Patch