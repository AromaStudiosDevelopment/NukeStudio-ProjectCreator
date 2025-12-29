# -*- coding: utf-8 -*-
"""Utility helpers shared across UI and loader code."""

from __future__ import absolute_import

import os
import re

LOCATION_PATTERN = re.compile(r'location\s*:\s*(.+)', re.IGNORECASE)
WORKFILE_PATTERN = re.compile(r'workfile\s*:\s*(.+)', re.IGNORECASE)
FIELD_BACKTICK_PATTERNS = {
    'location': re.compile(r'location[^`]*`([^`]+)`', re.IGNORECASE | re.DOTALL),
    'workfile': re.compile(r'workfile[^`]*`([^`]+)`', re.IGNORECASE | re.DOTALL),
}
IMAGE_SEQUENCE_PATTERN = re.compile(r'(.*?)([._-])?(%0\dd)')
BACKSLASH = '\\'
UNC_PREFIX = BACKSLASH * 2


def extract_location_from_comment(text):
    """Extract a media path from a conform comment."""
    return _extract_field_from_comment(text, 'location', LOCATION_PATTERN)


def extract_workfile_from_comment(text):
    """Extract a workfile path from task comments."""
    return _extract_field_from_comment(text, 'workfile', WORKFILE_PATTERN)


def _extract_field_from_comment(text, field_name, pattern):
    if not text:
        return None
    normalized = text.replace('\r', '')
    table_value = _extract_from_table(normalized, field_name)
    if table_value:
        return table_value
    line_value = _extract_from_pattern(normalized, pattern)
    if line_value:
        return line_value
    inline_value = _extract_from_inline_code(normalized, field_name)
    if inline_value:
        return inline_value
    return None


def _extract_from_table(text, field_name):
    lowered = field_name.lower()
    for raw_line in text.split('\n'):
        if '|' not in raw_line:
            continue
        parts = [cell.strip() for cell in raw_line.split('|') if cell.strip()]
        if len(parts) < 2:
            continue
        heading = parts[0].rstrip(':').strip().lower()
        if not heading.startswith(lowered):
            continue
        candidate = _clean_table_value(parts[1])
        if candidate:
            return candidate
    return None


def _extract_from_pattern(text, pattern):
    for line in text.split('\n'):
        match = pattern.search(line)
        if not match:
            continue
        candidate = _clean_table_value(match.group(1))
        if candidate:
            return candidate
    match = pattern.search(text)
    if match:
        return _clean_table_value(match.group(1))
    return None


def _extract_from_inline_code(text, field_name):
    regex = FIELD_BACKTICK_PATTERNS.get(field_name.lower())
    if not regex:
        return None
    match = regex.search(text)
    if match:
        return _clean_table_value(match.group(1))
    return None


def _clean_table_value(value):
    """Normalize markdown/table formatted entries."""
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
    if candidate.startswith(UNC_PREFIX):
        pass
    elif candidate.startswith(BACKSLASH):
        candidate = UNC_PREFIX + candidate.lstrip(BACKSLASH)
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
