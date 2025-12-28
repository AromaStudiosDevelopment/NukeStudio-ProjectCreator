# -*- coding: utf-8 -*-
"""Plugin bootstrap for the Kitsu Loader UI."""

from __future__ import absolute_import

import logging

try:
    from PySide2 import QtCore, QtWidgets  # pylint: disable=import-error
except ImportError:  # pragma: no cover - environment specific
    QtCore = None
    QtWidgets = None

try:
    import hiero.ui  # pylint: disable=import-error
except ImportError:  # pragma: no cover - environment specific
    hiero = None
else:
    import hiero  # type: ignore  # ensure hiero module available for typing

try:
    import nuke  # pylint: disable=import-error
except ImportError:  # pragma: no cover - environment specific
    nuke = None

from nuke_kitsu_loader.core import debug
from nuke_kitsu_loader.ui.main_widget import KitsuLoaderMainWidget
from nuke_kitsu_loader.ui.actions import register_actions


_PANEL_ID = "com.aromastudios.kitsu_loader"
_PANEL_NAME = "Kitsu Loader"
_MENU_PATH = "Custom/Kitsu Loader"
_WINDOW_INSTANCE = None
_MENU_REGISTERED = False
LOGGER = logging.getLogger(__name__)
debug.initialize()
LOGGER.info('Kitsu Loader plugin initialised; logs at %s', debug.current_log_file())


def _main_window():
    if hiero is not None and hasattr(hiero.ui, 'mainWindow'):
        try:
            return hiero.ui.mainWindow()
        except Exception:  # pragma: no cover - host controlled
            return None
    return None


if QtWidgets is not None:

    class KitsuLoaderWindow(QtWidgets.QDialog):  # type: ignore[misc]
        """Floating dialog that embeds the main loader widget."""

        def __init__(self, parent=None):
            super(KitsuLoaderWindow, self).__init__(parent)
            self.setObjectName(_PANEL_ID)
            self.setWindowTitle(_PANEL_NAME)
            if QtCore is not None:
                self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
            self.resize(540, 820)
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(KitsuLoaderMainWidget(parent=self))
            self.setLayout(layout)

else:  # pragma: no cover - PySide unavailable

    KitsuLoaderWindow = None


def create_panel(parent=None):
    """Create the loader widget, used by both pane and dialog modes."""
    if QtWidgets is None:
        raise RuntimeError("PySide2 is not available in this environment")
    return KitsuLoaderMainWidget(parent=parent)


def show_loader_window(force_new=False):
    """Show the loader as a PySide top-level window."""
    if QtWidgets is None:
        raise RuntimeError("PySide2 is not available in this environment")
    global _WINDOW_INSTANCE  # pylint: disable=global-statement
    if _WINDOW_INSTANCE is None or force_new:
        _WINDOW_INSTANCE = KitsuLoaderWindow(parent=_main_window())
    _WINDOW_INSTANCE.show()
    _WINDOW_INSTANCE.raise_()
    _WINDOW_INSTANCE.activateWindow()
    return _WINDOW_INSTANCE


def register_script_menu(menu_path=None):
    """Create a custom Nuke menu command that opens the loader window."""
    if QtWidgets is None:
        LOGGER.warning('PySide2 is unavailable; cannot create loader UI')
        return
    if nuke is None:
        LOGGER.warning('nuke module is unavailable; skipping menu registration')
        return
    global _MENU_REGISTERED  # pylint: disable=global-statement
    if _MENU_REGISTERED:
        return
    menu_label = menu_path or _MENU_PATH
    root_menu = nuke.menu('Nuke') if hasattr(nuke, 'menu') else None
    if root_menu is None:
        LOGGER.warning('Could not access Nuke menu; command %s not installed', menu_label)
        return

    def _open_window():
        show_loader_window()

    root_menu.addCommand(menu_label, _open_window)
    _MENU_REGISTERED = True
    if hiero is not None:
        register_actions()


def register_panel(menu_path=None):
    """Register the loader panel and ensure the custom script menu exists."""
    if QtWidgets is None:  # pragma: no cover - host specific
        return
    register_script_menu(menu_path)
    if hiero is None:
        return
    already_registered = hiero.ui.findMenuAction(_PANEL_NAME)
    if not already_registered:
        hiero.ui.addMenuAction(_PANEL_NAME, lambda: hiero.ui.openInPane(_PANEL_ID, create_panel))
        register_pane = getattr(hiero.ui, 'registerPaneWidget', None)
        register_pane_type = getattr(hiero.ui, 'registerPaneWidgetType', None)
        if callable(register_pane):
            register_pane(_PANEL_ID, create_panel, _PANEL_NAME)
        elif callable(register_pane_type):  # pragma: no cover - legacy host versions
            register_pane_type(_PANEL_NAME, create_panel)
        else:  # pragma: no cover - defensive fallback
            LOGGER.warning('Hiero UI does not expose registerPaneWidget; using menu action only.')
    register_actions()
