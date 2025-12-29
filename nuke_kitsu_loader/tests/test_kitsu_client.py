# -*- coding: utf-8 -*-
"""Unit tests for the kitsu_client helpers using fakes."""

from __future__ import absolute_import

import unittest

from nuke_kitsu_loader.core import kitsu_client, utils


class _FakeShotModule(object):
    def __init__(self, tasks_map):
        self._tasks_map = tasks_map

    def get_shot(self, shot_id):
        return {'id': shot_id}

    def all_shots_for_sequence(self, sequence):  # pragma: no cover - not used here
        return self._tasks_map.get(sequence.get('id'), [])
    
    def get_sequence(self, sequence_id):
        return {'id': sequence_id, 'name': 'Test Sequence'}


class _FakeTaskModule(object):
    def __init__(self, tasks_map, comments_map):
        self._tasks_map = tasks_map
        self._comments_map = comments_map

    def all_tasks_for_shot(self, shot):
        return self._tasks_map.get(shot.get('id'), [])
    
    def all_tasks_for_sequence(self, sequence):
        return self._tasks_map.get(sequence.get('id'), [])

    def all_comments_for_task(self, task):
        return list(self._comments_map.get(task.get('id'), []))

    def get_task_comments(self, task):  # pragma: no cover - compatibility shim
        return self.all_comments_for_task(task)


class _FakeGazu(object):
    def __init__(self, tasks_map, comments_map):
        self.task = _FakeTaskModule(tasks_map, comments_map)
        self.shot = _FakeShotModule(tasks_map)


class KitsuClientTests(unittest.TestCase):
    """Validate kitsu_client behavior with mocked gazu module."""

    def setUp(self):
        self._orig_gazu = kitsu_client.gazu
        self._orig_config = kitsu_client._CONFIG  # pylint: disable=protected-access
        self._tasks_map = {
            'shot-1': [
                {'id': 'task-10', 'task_type': {'name': 'Conforming'}},
                {'id': 'task-20', 'task_type': {'name': 'Compositing'}},
            ],
            'shot-2': [
                {'id': 'task-30', 'task_type': {'name': 'Lighting'}},
            ],
        }
        self._comments_map = {
            'task-10': [
                {'text': 'Legacy note', 'created_at': '2024-01-01T10:00:00'},
                {
                    'text': (
                        "Auto table\n"
                        "| Field | Value |\n"
                        "|---|---|\n"
                        "| Location | `/mnt/showA/seq01/shot010/plates/plate.mov` |\n"
                    ),
                    'created_at': '2024-02-01T10:00:00',
                },
            ],
            'task-20': [
                {
                    'text': (
                        "Publish\n"
                        "| Field | Value |\n"
                        "|---|---|\n"
                        "| Workfile | `/mnt/showA/seq01/shot010/comp/comp_v002.nk` |\n"
                    ),
                    'created_at': '2024-02-02T09:00:00',
                },
            ],
        }
        self._fake = _FakeGazu(self._tasks_map, self._comments_map)
        kitsu_client.gazu = self._fake
        kitsu_client._SESSION['logged_in'] = True  # pylint: disable=protected-access
        kitsu_client._CONFIG = {'path_mappings': [{'match': '/mnt', 'replace': r'\\\srv'}]}  # pylint: disable=protected-access

    def tearDown(self):
        kitsu_client.gazu = self._orig_gazu
        kitsu_client._SESSION['logged_in'] = False  # pylint: disable=protected-access
        kitsu_client._CONFIG = self._orig_config  # pylint: disable=protected-access

    def test_get_latest_conform_comment_prefers_latest_table_entry(self):
        ok, text = kitsu_client.get_latest_conform_comment('shot-1')
        self.assertTrue(ok)
        extracted = utils.extract_location_from_comment(text)
        self.assertEqual(extracted, r'/mnt/showA/seq01/shot010/plates/plate.mov')

    def test_get_latest_workfile_uses_comments_and_mappings(self):
        ok, path = kitsu_client.get_latest_workfile_for_shot('shot-1', 'Compositing')
        self.assertTrue(ok)
        self.assertEqual(path, r'\\\srv/showA/seq01/shot010/comp/comp_v002.nk')

    def test_get_latest_workfile_returns_none_when_task_missing(self):
        ok, path = kitsu_client.get_latest_workfile_for_shot('shot-2', 'Compositing')
        self.assertTrue(ok)
        self.assertIsNone(path)

    def test_get_tasks_for_sequence_filters_2d_tasks_when_enabled(self):
        """Test that only 2D task types are returned when filter is enabled."""
        # Setup sequence with mixed 2D and 3D tasks
        self._tasks_map['seq-1'] = [
            {'id': 'task-1', 'task_type': {'id': 'tt-1', 'name': 'Conform'}},
            {'id': 'task-2', 'task_type': {'id': 'tt-2', 'name': 'Compositing'}},
            {'id': 'task-3', 'task_type': {'id': 'tt-3', 'name': 'Lighting'}},
            {'id': 'task-4', 'task_type': {'id': 'tt-4', 'name': 'Animation'}},
            {'id': 'task-5', 'task_type': {'id': 'tt-5', 'name': 'Roto'}},
        ]
        # Enable filter with 2D task types
        kitsu_client._CONFIG = {  # pylint: disable=protected-access
            'task_type_filter': {
                'enabled': True,
                'allowed_task_types': ['Conform', 'Compositing', 'Roto']
            }
        }
        
        ok, tasks = kitsu_client.get_tasks_for_sequence('seq-1')
        self.assertTrue(ok)
        task_names = [t['name'] for t in tasks]
        # Should only include 2D tasks
        self.assertIn('Conform', task_names)
        self.assertIn('Compositing', task_names)
        self.assertIn('Roto', task_names)
        # Should exclude 3D tasks
        self.assertNotIn('Lighting', task_names)
        self.assertNotIn('Animation', task_names)
        self.assertEqual(len(tasks), 3)

    def test_get_tasks_for_sequence_returns_all_when_filter_disabled(self):
        """Test that all task types are returned when filter is disabled."""
        self._tasks_map['seq-2'] = [
            {'id': 'task-1', 'task_type': {'id': 'tt-1', 'name': 'Conform'}},
            {'id': 'task-2', 'task_type': {'id': 'tt-2', 'name': 'Lighting'}},
            {'id': 'task-3', 'task_type': {'id': 'tt-3', 'name': 'Animation'}},
        ]
        # Disable filter
        kitsu_client._CONFIG = {  # pylint: disable=protected-access
            'task_type_filter': {
                'enabled': False,
                'allowed_task_types': ['Conform']
            }
        }
        
        ok, tasks = kitsu_client.get_tasks_for_sequence('seq-2')
        self.assertTrue(ok)
        task_names = [t['name'] for t in tasks]
        # Should include all tasks when filter is disabled
        self.assertIn('Conform', task_names)
        self.assertIn('Lighting', task_names)
        self.assertIn('Animation', task_names)
        self.assertEqual(len(tasks), 3)

    def test_get_tasks_for_sequence_returns_all_when_no_filter_config(self):
        """Test that all task types are returned when no filter config exists."""
        self._tasks_map['seq-3'] = [
            {'id': 'task-1', 'task_type': {'id': 'tt-1', 'name': 'Conform'}},
            {'id': 'task-2', 'task_type': {'id': 'tt-2', 'name': 'Lighting'}},
        ]
        # No filter config
        kitsu_client._CONFIG = {}  # pylint: disable=protected-access
        
        ok, tasks = kitsu_client.get_tasks_for_sequence('seq-3')
        self.assertTrue(ok)
        self.assertEqual(len(tasks), 2)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
