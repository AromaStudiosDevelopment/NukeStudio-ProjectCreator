# -*- coding: utf-8 -*-
"""Main dockable widget for the Kitsu loader."""

from __future__ import absolute_import

from PySide2 import QtCore, QtWidgets  # pylint: disable=import-error

from nuke_kitsu_loader.core import debug, kitsu_client
from nuke_kitsu_loader.core.loader import LoaderThread, MainThreadExecutor
from nuke_kitsu_loader.ui.login_widget import LoginWidget
from nuke_kitsu_loader.ui.sequence_card import SequenceCard

try:
    unicode  # type: ignore
except NameError:  # pragma: no cover
    unicode = str


class KitsuLoaderMainWidget(QtWidgets.QWidget):
    """Container widget that orchestrates login and sequence loading."""

    def __init__(self, parent=None):
        super(KitsuLoaderMainWidget, self).__init__(parent)
        self._login_widget = LoginWidget(self)
        self._login_widget.setVisible(False)  # Hide authentication UI
        self._project_combo = QtWidgets.QComboBox(self)
        self._project_combo.setEnabled(False)
        self._project_status = QtWidgets.QLabel('No projects loaded', self)
        self._load_button = QtWidgets.QPushButton('Load Selected Sequences', self)
        self._load_button.setEnabled(False)
        self._log_output = QtWidgets.QTextEdit(self)
        self._log_output.setReadOnly(True)
        self._sequence_container = QtWidgets.QWidget(self)
        self._sequence_layout = QtWidgets.QVBoxLayout(self._sequence_container)
        self._sequence_layout.addStretch()
        self._sequence_scroll = QtWidgets.QScrollArea(self)
        self._sequence_scroll.setWidgetResizable(True)
        self._sequence_scroll.setWidget(self._sequence_container)
        self._loader_thread = None
        self._sequence_cards = []
        self._main_thread_executor = MainThreadExecutor()
        self._current_project = None

        self._build_layout()
        self._connect_signals()
        self._announce_log_location()
        
        # Auto-login on initialization
        QtCore.QTimer.singleShot(100, self._auto_login)

    def _build_layout(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._login_widget)
        project_row = QtWidgets.QHBoxLayout()
        project_row.addWidget(QtWidgets.QLabel('Project', self))
        project_row.addWidget(self._project_combo)
        project_row.addWidget(self._project_status)
        layout.addLayout(project_row)
        layout.addWidget(self._sequence_scroll)
        layout.addWidget(self._load_button)
        layout.addWidget(self._log_output)
        self.setLayout(layout)

    def _connect_signals(self):
        self._login_widget.login_successful.connect(self._on_login_success)
        self._login_widget.login_failed.connect(self._append_log)
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)
        self._load_button.clicked.connect(self._start_loader)

    def _on_login_success(self, context):
        self._append_log('Login successful for %s' % context.get('user', {}).get('display_name'))
        self._project_combo.clear()
        ok, payload = kitsu_client.get_projects()
        if not ok:
            self._project_status.setText(unicode(payload))
            self._project_combo.setEnabled(False)
            return
        for project in payload:
            self._project_combo.addItem(project['name'], project)
        self._project_combo.setEnabled(True)
        self._project_status.setText('%d projects loaded' % len(payload))
        self._load_button.setEnabled(False)
        if self._project_combo.count():
            self._project_combo.setCurrentIndex(0)

    def _append_log(self, message):
        self._log_output.append(unicode(message))

    def _announce_log_location(self):
        log_path = debug.current_log_file()
        if log_path:
            self._append_log('Debug log file: %s' % log_path)

    def _auto_login(self):
        """Automatically trigger login using environment variables."""
        self._append_log('Attempting auto-login...')
        self._login_widget._attempt_login()

    def _on_project_changed(self, index):
        project = self._project_combo.itemData(index)
        if not project:
            self._append_log('Select a project to continue')
            self._clear_sequence_cards()
            self._load_button.setEnabled(False)
            return
        self._append_log('Loading sequences for %s' % project.get('name'))
        ok, payload = kitsu_client.get_sequences(project.get('id'))
        if not ok:
            self._project_status.setText(unicode(payload))
            self._clear_sequence_cards()
            self._load_button.setEnabled(False)
            return
        self._populate_sequence_cards(payload)
        self._load_button.setEnabled(bool(payload))

    def _start_loader(self):
        if self._loader_thread and self._loader_thread.isRunning():
            self._append_log('Loader already running')
            return
        selections = self._collect_selected_sequences()
        if not selections:
            self._append_log('Select at least one sequence before loading')
            return
        self._append_log('Starting loader for %d sequence(s)' % len(selections))
        self._load_button.setEnabled(False)
        self._loader_thread = LoaderThread(selections, self._main_thread_executor)
        self._loader_thread.message.connect(self._append_log)
        self._loader_thread.progress.connect(self._on_progress)
        self._loader_thread.completed.connect(self._on_completed)
        self._loader_thread.errored.connect(self._on_error)
        self._loader_thread.start()

    def _on_progress(self, value):
        self._append_log('Progress: %d%%' % value)

    def _on_completed(self, summary):
        self._append_log('Loader finished: %s' % summary)
        self._load_button.setEnabled(True)
        self._loader_thread = None

    def _on_error(self, payload):
        self._append_log('ERROR: %s' % unicode(payload.get('message', 'Unknown error')))

    def _clear_sequence_cards(self):
        while self._sequence_cards:
            card = self._sequence_cards.pop()
            self._sequence_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()

    def _populate_sequence_cards(self, sequences):
        self._clear_sequence_cards()
        for sequence in sequences:
            card = SequenceCard(sequence.get('id'), sequence.get('name'), self._sequence_container)
            insert_at = max(0, self._sequence_layout.count() - 1)
            self._sequence_layout.insertWidget(insert_at, card)
            self._sequence_cards.append(card)
        if self._sequence_cards:
            self._project_status.setText('%d sequences ready' % len(self._sequence_cards))
        else:
            self._project_status.setText('No sequences found')

    def _collect_selected_sequences(self):
        selections = []
        for card in self._sequence_cards:
            if not card.is_selected():
                continue
            selected_tasks = card.selected_tasks()
            if not selected_tasks:
                continue
            selections.append({
                'id': card.sequence_id(),
                'name': card.sequence_name(),
                'tasks': selected_tasks,  # Now a list of task names
            })
        return selections
