# -*- coding: utf-8 -*-
"""Thin wrapper around the Gazu client to keep UI code simple."""

from __future__ import absolute_import

import json
import logging
import os

try:
    import gazu  # pylint: disable=import-error
except ImportError:  # pragma: no cover - gazu not vendorized yet
    gazu = None

LOGGER = logging.getLogger(__name__)

_CONFIG = None
_SESSION = {
    'host': None,
    'user': None,
    'logged_in': False,
}


def _load_config():
    """Lazy-load plugin configuration."""
    global _CONFIG  # pylint: disable=global-statement
    if _CONFIG is not None:
        return _CONFIG
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'configs', 'plugin_config.json')
    if not os.path.exists(config_path):
        _CONFIG = {}
        return _CONFIG
    try:
        with open(config_path, 'r') as handle:
            _CONFIG = json.load(handle)
    except Exception as exc:  # pragma: no cover - config parsing errors
        LOGGER.error('Failed to load config %s: %s', config_path, exc)
        _CONFIG = {}
    return _CONFIG


def _gazu_available():
    if gazu is None:
        return False, 'gazu module is not available. Install or vendor it before continuing.'
    return True, None


def _ensure_session():
    if not _SESSION['logged_in']:
        return False, 'You must log in to Kitsu before making API calls.'
    return True, None


def login(host, username, password):
    """Authenticate against the configured Kitsu instance."""
    ok, error = _gazu_available()
    if not ok:
        return False, error
    try:
        gazu.set_host(host)
        user = gazu.log_in(username, password)
    except Exception as exc:  # pragma: no cover - depends on network state
        LOGGER.exception('Login failed: %s', exc)
        return False, str(exc)
    _SESSION['host'] = host
    _SESSION['user'] = {'id': user.get('id'), 'display_name': user.get('full_name') or user.get('name')}
    _SESSION['logged_in'] = True
    return True, _SESSION['user']


def logout():
    """Log out of the current session."""
    if gazu is None:  # pragma: no cover - mirrors login guard
        return
    try:
        gazu.log_out()
    except Exception as exc:  # pragma: no cover
        LOGGER.warning('Error during logout: %s', exc)
    finally:
        _SESSION['host'] = None
        _SESSION['user'] = None
        _SESSION['logged_in'] = False


def get_projects():
    """Return all projects visible to the current user."""
    ok, error = _ensure_session()
    if not ok:
        return False, error
    try:
        projects = gazu.project.all_projects()
    except Exception as exc:  # pragma: no cover - depends on API
        LOGGER.exception('Failed to fetch projects: %s', exc)
        return False, str(exc)
    payload = [
        {
            'id': project.get('id'),
            'name': project.get('name'),
            'data': project,
        }
        for project in projects
    ]
    return True, payload


def get_sequences(project_id):
    """Return sequences for the given project."""
    ok, error = _ensure_session()
    if not ok:
        return False, error
    try:
        project = gazu.project.get_project(project_id)
        sequences = gazu.shot.all_sequences(project)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception('Failed to fetch sequences for %s: %s', project_id, exc)
        return False, str(exc)
    payload = [
        {
            'id': sequence.get('id'),
            'name': sequence.get('name'),
            'data': sequence,
        }
        for sequence in sequences
    ]
    return True, payload


def get_tasks_for_sequence(sequence_id):
    """Return distinct task names associated with the sequence.
    
    Filters tasks to only include 2D-relevant task types if task_type_filter
    is enabled in the configuration.
    """
    ok, error = _ensure_session()
    if not ok:
        return False, error
    try:
        sequence = gazu.shot.get_sequence(sequence_id)
        tasks = gazu.task.all_tasks_for_sequence(sequence)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception('Failed to fetch tasks for %s: %s', sequence_id, exc)
        return False, str(exc)
    
    # Load filter configuration
    config = _load_config()
    filter_config = config.get('task_type_filter', {})
    filter_enabled = filter_config.get('enabled', False)
    allowed_task_types = filter_config.get('allowed_task_types', [])
    
    seen = set()
    ordered = []
    for task in tasks:
        task_type = task.get('task_type') or {}
        name = task_type.get('name')
        if not name or name in seen:
            continue
        # Apply filter if enabled: ensuring 2D task types
        if filter_enabled and allowed_task_types:
            if name not in allowed_task_types:
                continue
        seen.add(name)
        ordered.append({'id': task_type.get('id'), 'name': name})
    return True, ordered


def get_shots_for_sequence(sequence_id):
    """Return shots for a sequence ordered by their display name."""
    ok, error = _ensure_session()
    if not ok:
        return False, error
    try:
        sequence = gazu.shot.get_sequence(sequence_id)
        shots = gazu.shot.all_shots_for_sequence(sequence)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception('Failed to fetch shots for %s: %s', sequence_id, exc)
        return False, str(exc)
    shots = sorted(shots, key=lambda shot: shot.get('name') or shot.get('code') or '')
    payload = [
        {
            'id': shot.get('id'),
            'name': shot.get('name') or shot.get('code'),
            'data': shot,
        }
        for shot in shots
    ]
    return True, payload


def get_latest_conform_comment(shot_id):
    """Return the newest conform comment body for the given shot."""
    ok, error = _ensure_session()
    if not ok:
        return False, error
    try:
        shot = gazu.shot.get_shot(shot_id)
        tasks = gazu.task.all_tasks_for_shot(shot)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception('Failed to fetch tasks for shot %s: %s', shot_id, exc)
        return False, str(exc)
    conform_tasks = []
    for task in tasks:
        task_type = task.get('task_type') or {}
        if (task_type.get('name') or '').lower() == 'conform':
            conform_tasks.append(task)
    if not conform_tasks:
        return True, None
    comments = []
    for task in conform_tasks:
        try:
            comments.extend(gazu.task.get_task_comments(task))
        except Exception as exc:  # pragma: no cover
            LOGGER.warning('Failed to fetch comments for task %s: %s', task.get('id'), exc)
    if not comments:
        return True, None
    comments = sorted(
        comments,
        key=lambda comment: comment.get('created_at') or comment.get('updated_at') or '',
    )
    latest = comments[-1]
    text = latest.get('text') or latest.get('description') or latest.get('content')
    return True, text


def get_latest_workfile_for_shot(shot_id, task_name):
    """Return the newest workfile path for the given shot/task."""
    ok, error = _ensure_session()
    if not ok:
        return False, error
    if not task_name:
        return True, None
    try:
        shot = gazu.shot.get_shot(shot_id)
        tasks = gazu.task.all_tasks_for_shot(shot)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception('Failed to fetch tasks for shot %s: %s', shot_id, exc)
        return False, str(exc)
    desired = task_name.lower()
    task_candidates = [task for task in tasks if (task.get('task_type', {}).get('name') or '').lower() == desired]
    for task in task_candidates:
        workfile_path = _latest_workfile_from_task(task)
        if workfile_path:
            return True, workfile_path
    return True, None


def translate_repo_path_to_unc(path_value):
    """Translate a repository path into a UNC path based on config mappings."""
    if not path_value:
        return path_value
    config = _load_config()
    mappings = config.get('path_mappings', [])
    for mapping in mappings:
        match_value = mapping.get('match')
        replace_value = mapping.get('replace')
        if not match_value or not replace_value:
            continue
        if path_value.startswith(match_value):
            return path_value.replace(match_value, replace_value, 1)
    return path_value


def _latest_workfile_from_task(task):
    files_module = getattr(gazu, 'files', None)
    if files_module is None:
        return None
    try:
        workfile = files_module.get_last_working_file(task)
    except Exception:  # pragma: no cover - depends on API version
        workfile = None
    if workfile:
        return workfile.get('file_path') or workfile.get('path') or workfile.get('full_path')
    try:
        workfiles = files_module.get_working_files(task)
    except Exception:  # pragma: no cover
        return None
    if not workfiles:
        return None
    workfiles = sorted(workfiles, key=lambda item: item.get('updated_at') or item.get('created_at') or '')
    latest = workfiles[-1]
    return latest.get('file_path') or latest.get('path') or latest.get('full_path')
