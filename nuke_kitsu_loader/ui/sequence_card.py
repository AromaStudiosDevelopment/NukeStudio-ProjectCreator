# -*- coding: utf-8 -*-
"""Sequence card widget used in later phases."""

from __future__ import absolute_import

from PySide2 import QtWidgets  # pylint: disable=import-error


DEFAULT_2D_TASKS = [
    {'id': 'compositing', 'name': 'Compositing'},
    {'id': 'roto_keying', 'name': 'Roto_Keying'},
    {'id': 'cleanup', 'name': 'Cleanup'},
]


class SequenceCard(QtWidgets.QWidget):
    """Displays a sequence name, task checkboxes, and include checkbox."""

    def __init__(self, sequence_id, sequence_name, parent=None):
        super(SequenceCard, self).__init__(parent)
        self._sequence_id = sequence_id
        self._sequence_name = sequence_name
        self._label = QtWidgets.QLabel(sequence_name, self)
        self._label.setMinimumWidth(150)
        
        # Task checkboxes
        self._task_checkboxes = {}
        self._task_container = QtWidgets.QWidget(self)
        self._task_layout = QtWidgets.QHBoxLayout(self._task_container)
        self._task_layout.setContentsMargins(0, 0, 0, 0)
        
        for task in DEFAULT_2D_TASKS:
            checkbox = QtWidgets.QCheckBox(task['name'], self)
            self._task_checkboxes[task['name']] = checkbox
            self._task_layout.addWidget(checkbox)
        
        self._include = QtWidgets.QCheckBox('Include', self)
        self._include.setChecked(True)
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._task_container)
        layout.addStretch()
        layout.addWidget(self._include)
        self.setLayout(layout)

    def is_selected(self):
        return self._include.isChecked()

    def selected_tasks(self):
        """Return list of selected task names."""
        return [name for name, checkbox in self._task_checkboxes.items() if checkbox.isChecked()]

    def sequence_name(self):
        return self._sequence_name

    def sequence_id(self):
        return self._sequence_id
