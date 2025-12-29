# -*- coding: utf-8 -*-
"""Login UI for the Kitsu loader."""

from __future__ import absolute_import

import os

from PySide2 import QtCore, QtWidgets  # pylint: disable=import-error

from nuke_kitsu_loader.core import kitsu_client

try:
    unicode  # type: ignore
except NameError:  # pragma: no cover - Python 3 compatibility for tooling
    unicode = str


class LoginWidget(QtWidgets.QWidget):
    """Collects Kitsu credentials from environment variables and emits success/failure signals."""

    login_successful = QtCore.Signal(dict)
    login_failed = QtCore.Signal(unicode)

    def __init__(self, parent=None):
        super(LoginWidget, self).__init__(parent)
        self._login_button = QtWidgets.QPushButton('Login from Environment', self)
        self._status = QtWidgets.QLabel('Not logged in', self)
        self._info_label = QtWidgets.QLabel(
            'Credentials will be read from environment variables:\n'
            'KITSU_SERVER, KITSU_LOGIN, KITSU_PWD',
            self
        )

        self._build_layout()
        self._login_button.clicked.connect(self._attempt_login)

    def _build_layout(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._info_label)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self._login_button)
        button_row.addWidget(self._status)
        layout.addLayout(button_row)
        self.setLayout(layout)

    def _attempt_login(self):
        self._set_busy(True)
        # Read credentials from environment variables
        host = os.environ.get('KITSU_SERVER', '').strip()
        username = os.environ.get('KITSU_LOGIN', '').strip()
        password = os.environ.get('KITSU_PWD', '').strip()
        
        if not host or not username or not password:
            self._set_busy(False)
            message = 'Missing environment variables. Please set KITSU_SERVER, KITSU_LOGIN, and KITSU_PWD.'
            self._status.setText(message)
            self.login_failed.emit(unicode(message))
            return
        
        ok, payload = kitsu_client.login(host, username, password)
        self._set_busy(False)
        if ok:
            self._status.setText('Logged in as %s' % payload.get('display_name'))
            self.login_successful.emit({'host': host, 'user': payload})
        else:
            message = unicode(payload)
            self._status.setText(message)
            self.login_failed.emit(message)

    def _set_busy(self, busy):
        self._login_button.setEnabled(not busy)
        cursor = QtCore.Qt.WaitCursor if busy else QtCore.Qt.ArrowCursor
        self.setCursor(cursor)
