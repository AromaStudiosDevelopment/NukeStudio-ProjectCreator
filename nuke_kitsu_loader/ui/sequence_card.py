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
    """Displays a sequence name, task selector, and include checkbox."""

    def __init__(self, sequence_id, sequence_name, parent=None):
        super(SequenceCard, self).__init__(parent)
        self._sequence_id = sequence_id
        self._sequence_name = sequence_name
        self._label = QtWidgets.QLabel(sequence_name, self)
        self._task_combo = QtWidgets.QComboBox(self)
        self._include = QtWidgets.QCheckBox('Include', self)
        self._include.setChecked(True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._task_combo)
        layout.addWidget(self._include)
        self.setLayout(layout)
        self.set_tasks(DEFAULT_2D_TASKS)

    def set_tasks(self, tasks):
        self._task_combo.clear()
        for task in tasks or []:
            self._task_combo.addItem(task.get('name'), task)

    def is_selected(self):
        return self._include.isChecked()

    def selected_task(self):
        data = self._task_combo.currentData()
        if data is None:
            return {'name': self._task_combo.currentText()}
        return data

    def sequence_name(self):
        return self._sequence_name

    def sequence_id(self):
        return self._sequence_id
