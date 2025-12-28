# -*- coding: utf-8 -*-
"""Login UI for the Kitsu loader."""

from __future__ import absolute_import

from PySide2 import QtCore, QtWidgets  # pylint: disable=import-error

from nuke_kitsu_loader.core import kitsu_client

try:
    unicode  # type: ignore
except NameError:  # pragma: no cover - Python 3 compatibility for tooling
    unicode = str


class LoginWidget(QtWidgets.QWidget):
    """Collects Kitsu credentials and emits success/failure signals."""

    login_successful = QtCore.Signal(dict)
    login_failed = QtCore.Signal(unicode)

    def __init__(self, parent=None):
        super(LoginWidget, self).__init__(parent)
        self._host = QtWidgets.QLineEdit(self)
        self._username = QtWidgets.QLineEdit(self)
        self._password = QtWidgets.QLineEdit(self)
        self._password.setEchoMode(QtWidgets.QLineEdit.Password)
        self._login_button = QtWidgets.QPushButton('Login', self)
        self._status = QtWidgets.QLabel('Not logged in', self)

        self._build_layout()
        self._login_button.clicked.connect(self._attempt_login)

        default_host = kitsu_client.get_default_host() or ''
        if default_host:
            self._host.setText(default_host)
            self._host.setReadOnly(True)
            self._host.setToolTip('Update configs/plugin_config.json to change the Kitsu host')
        else:
            self._host.setPlaceholderText('Set kitsu_host in configs/plugin_config.json')
            self._host.setReadOnly(True)

    def _build_layout(self):
        layout = QtWidgets.QFormLayout(self)
        layout.addRow('Kitsu Host', self._host)
        layout.addRow('Username', self._username)
        layout.addRow('Password', self._password)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self._login_button)
        button_row.addWidget(self._status)
        layout.addRow(button_row)
        self.setLayout(layout)

    def _attempt_login(self):
        self._set_busy(True)
        host = kitsu_client.get_default_host()
        username = self._username.text().strip()
        password = self._password.text().strip()
        if not host:
            message = 'kitsu_host is not configured. Edit configs/plugin_config.json.'
            self._status.setText(message)
            self.login_failed.emit(unicode(message))
            self._set_busy(False)
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
