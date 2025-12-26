# -*- coding: utf-8 -*-
"""Utility helpers shared across UI and loader code."""

from __future__ import absolute_import

import os
import re

LOCATION_PATTERN = re.compile(r'location\s*:\s*(.+)', re.IGNORECASE)
IMAGE_SEQUENCE_PATTERN = re.compile(r'(.*?)([._-])?(%0\dd)' % 4)


def extract_location_from_comment(text):
    """Extract a media path from a conform comment."""
    if not text:
        return None
    match = LOCATION_PATTERN.search(text)
    if not match:
        return None
    candidate = match.group(1).strip()
    candidate = candidate.rstrip(' ;.,')
    return candidate or None


def is_image_sequence(path_value):
    """Best-effort detection of image sequence patterns."""
    if not path_value:
        return False, None
    if '%' in path_value and 'd' in path_value:
        return True, path_value
    sequence_match = re.search(r'(#+)', path_value)
    if sequence_match:
        return True, path_value[:sequence_match.start()] + '%0{}d'.format(len(sequence_match.group(1))) + path_value[sequence_match.end():]
    return False, None


def normalize_path(path_value, mapping_config):
    """Apply mapping rules to convert repo paths to UNC equivalents."""
    if not path_value:
        return path_value
    mappings = mapping_config or []
    for mapping in mappings:
        match_value = mapping.get('match')
        replace_value = mapping.get('replace')
        if not match_value or not replace_value:
            continue
        if path_value.startswith(match_value):
            return path_value.replace(match_value, replace_value, 1)
    return path_value


def path_exists(path_value):
    """Wrapper that can be monkey-patched for unit tests."""
    if not path_value:
        return False
    return os.path.exists(path_value)
