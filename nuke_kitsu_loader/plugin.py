# -*- coding: utf-8 -*-
"""Plugin bootstrap for the Kitsu Loader panel."""

from __future__ import absolute_import

import logging

try:
    from PySide2 import QtWidgets  # pylint: disable=import-error
except ImportError:  # pragma: no cover - environment specific
    QtWidgets = None

try:
    import hiero.ui  # pylint: disable=import-error
except ImportError:  # pragma: no cover - environment specific
    hiero = None
else:
    import hiero  # type: ignore  # ensure hiero module available for typing

from nuke_kitsu_loader.ui.main_widget import KitsuLoaderMainWidget
from nuke_kitsu_loader.ui.actions import register_actions


_PANEL_ID = "com.aromastudios.kitsu_loader"
_PANEL_NAME = "Kitsu Loader"
LOGGER = logging.getLogger(__name__)


def create_panel(parent=None):
    """Create the dockable widget when requested by Hiero."""
    if QtWidgets is None:
        raise RuntimeError("PySide2 is not available in this environment")
    return KitsuLoaderMainWidget(parent=parent)


def register_panel():
    """Register the panel with Hiero/Nuke Studio if possible."""
    if hiero is None or QtWidgets is None:  # pragma: no cover - host specific
        return
    already_registered = hiero.ui.findMenuAction(_PANEL_NAME)
    if already_registered:
        return
    hiero.ui.addMenuAction(_PANEL_NAME, lambda: hiero.ui.openInPane(_PANEL_ID, create_panel))
    register_pane = getattr(hiero.ui, 'registerPaneWidget', None)
    register_pane_type = getattr(hiero.ui, 'registerPaneWidgetType', None)
    if callable(register_pane):
        register_pane(_PANEL_ID, create_panel, _PANEL_NAME)
    elif callable(register_pane_type):  # pragma: no cover - legacy host versions
        register_pane_type(_PANEL_NAME, create_panel)
    else:  # pragma: no cover - defensive fallback
        LOGGER.warning('Hiero UI does not expose registerPaneWidget; panel can only be opened via menu action.')
    register_actions()
