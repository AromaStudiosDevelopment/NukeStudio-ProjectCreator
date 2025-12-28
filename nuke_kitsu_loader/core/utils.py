# -*- coding: utf-8 -*-
"""Utility helpers shared across UI and loader code."""

from __future__ import absolute_import

import os
import re

LOCATION_PATTERN = re.compile(r'location\s*:\s*(.+)', re.IGNORECASE)
IMAGE_SEQUENCE_PATTERN = re.compile(r'(.*?)([._-])?(%0\d+d)')


def extract_location_from_comment(text):
    """Extract a media path from a conform comment."""
    if not text:
        return None
    normalized = text.replace('\r', '')
    for line in normalized.split('\n'):
        match = LOCATION_PATTERN.search(line)
        if not match:
            continue
        candidate = _clean_location_candidate(match.group(1))
        if candidate:
            return candidate
    match = LOCATION_PATTERN.search(normalized)
    if match:
        return _clean_location_candidate(match.group(1))
    return None


def _clean_location_candidate(value):
    """Normalize markdown/table formatted location entries."""
    if not value:
        return None
    candidate = value.strip()
    candidate = candidate.strip('|').strip()
    if '|' in candidate:
        candidate = candidate.split('|', 1)[0].strip()
    if candidate.startswith('`') and candidate.endswith('`'):
        candidate = candidate[1:-1].strip()
    candidate = candidate.strip('`" ')
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
