# -*- coding: utf-8 -*-
"""Unit tests for nuke_kitsu_loader.core.utils."""

from __future__ import absolute_import

import os
import tempfile
import unittest

from nuke_kitsu_loader.core import utils


class UtilsTests(unittest.TestCase):
    """Exercise parser and path helpers."""

    def test_extract_location_from_comment_unc(self):
        text = "Some note\nlocation: \\server\\share\\plate.mov\nMore"
        self.assertEqual(utils.extract_location_from_comment(text), "\\\\server\\share\\plate.mov")

    def test_extract_location_returns_none_when_missing(self):
        self.assertIsNone(utils.extract_location_from_comment("No keyword here"))

    def test_is_image_sequence_detects_hash_pattern(self):
        is_seq, pattern = utils.is_image_sequence('/path/shot.####.exr')
        self.assertTrue(is_seq)
        self.assertEqual(pattern, '/path/shot.%04d.exr')

    def test_normalize_path_applies_first_matching_rule(self):
        mapping = [{'match': '/repo', 'replace': r'\\\host\\repo'}]
        self.assertEqual(utils.normalize_path('/repo/show/shot', mapping), r'\\\host\\repo/show/shot')

    def test_path_exists_wrapper(self):
        handle, path = tempfile.mkstemp()
        os.close(handle)
        try:
            self.assertTrue(utils.path_exists(path))
        finally:
            os.unlink(path)

    def test_extract_workfile_from_comment(self):
        text = "Workfile: \\\\192.168.150.179\\share2\\release\\gizmo_10_v02.nk"
        self.assertEqual(utils.extract_workfile_from_comment(text), "\\\\192.168.150.179\\share2\\release\\gizmo_10_v02.nk")

    def test_extract_workfile_returns_none_when_missing(self):
        self.assertIsNone(utils.extract_workfile_from_comment("No workfile keyword here"))

    def test_parse_task_comment_with_both_fields(self):
        text = "Workfile: \\\\192.168.150.179\\share2\\release\\gizmo_10_v02.nk\nLocation: \\\\192.168.150.179\\share2\\footage\\A002_C018_0922BW_002.mov"
        result = utils.parse_task_comment(text)
        self.assertEqual(result['workfile'], "\\\\192.168.150.179\\share2\\release\\gizmo_10_v02.nk")
        self.assertEqual(result['location'], "\\\\192.168.150.179\\share2\\footage\\A002_C018_0922BW_002.mov")

    def test_parse_task_comment_with_only_location(self):
        text = "Location: \\\\192.168.150.179\\share2\\footage\\render.mov"
        result = utils.parse_task_comment(text)
        self.assertIsNone(result['workfile'])
        self.assertEqual(result['location'], "\\\\192.168.150.179\\share2\\footage\\render.mov")

    def test_parse_task_comment_with_only_workfile(self):
        text = "Workfile: \\\\server\\path\\script.nk"
        result = utils.parse_task_comment(text)
        self.assertEqual(result['workfile'], "\\\\server\\path\\script.nk")
        self.assertIsNone(result['location'])


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
