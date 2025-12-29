# -*- coding: utf-8 -*-
"""Centralised debugging helpers for the Kitsu loader."""

from __future__ import absolute_import

import datetime
import json
import logging
import os
import sys
import time
import traceback

try:  # pragma: no cover - PySide optional when running tests
    from PySide2 import QtCore  # pylint: disable=import-error
except ImportError:  # pragma: no cover - tests/CLI
    QtCore = None

try:  # pragma: no cover - Python 3 tooling support
    unicode
except NameError:  # pragma: no cover
    unicode = str

_LOG_STATE = {
    'configured': False,
    'log_path': None,
    'log_dir': None,
    'summary_dir': None,
    'previous_hook': None,
    'qt_handler_installed': False,
    'qt_message_cache': {},
}
DEFAULT_LOG_DIRNAME = 'kitsu_loader_logs'
DEFAULT_SUMMARY_DIRNAME = 'kitsu_loader_runs'
_QT_REPEAT_LIMIT = 5
_QT_SUPPRESS_INTERVAL = 25
_QT_RESET_SECONDS = 5.0
_QT_DISABLE_ENV = 'KITSU_LOADER_DISABLE_QT_LOG'
LOGGER = logging.getLogger(__name__)


def initialize(debug_name='kitsu_loader'):
    """Ensure logging/exception hooks are configured.

    Returns:
        str: Path to the current log file (best-effort).
    """
    if _LOG_STATE['configured']:
        return _LOG_STATE['log_path']
    log_dir = _ensure_directory(os.path.join(_user_home(), DEFAULT_LOG_DIRNAME))
    summary_dir = _ensure_directory(os.path.join(_user_home(), DEFAULT_SUMMARY_DIRNAME))
    timestamp = datetime.datetime.now().strftime('%Y%m%d')
    log_path = os.path.join(log_dir, '%s_%s.log' % (debug_name, timestamp))
    handler = logging.FileHandler(log_path)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    _LOG_STATE.update({
        'configured': True,
        'log_path': log_path,
        'log_dir': log_dir,
        'summary_dir': summary_dir,
    })
    _install_exception_hook()
    _install_qt_message_handler()
    LOGGER.info('Debug logging initialised: %s', log_path)
    return log_path


def current_log_file():
    """Return the active log file path, if configured."""
    return _LOG_STATE.get('log_path')


def record_exception(context_label, exc_info=None):
    """Log an unexpected exception and return a structured payload."""
    initialize()
    if exc_info is None:
        exc_info = sys.exc_info()
    trace_text = None
    if exc_info and exc_info[0]:
        trace_text = ''.join(traceback.format_exception(*exc_info))
        LOGGER.error('Unhandled exception in %s', context_label, exc_info=exc_info)
    payload = {
        'context': context_label,
        'log_file': current_log_file(),
        'traceback': trace_text,
    }
    return payload


def write_run_summary(summary, filename_prefix='loader_run'):
    """Persist a JSON snapshot of the loader summary for offline debugging."""
    initialize()
    summary_dir = _LOG_STATE.get('summary_dir')
    if not summary_dir:
        return None
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    file_path = os.path.join(summary_dir, '%s_%s.json' % (filename_prefix, timestamp))
    safe_summary = _sanitize(summary)
    try:
        with open(file_path, 'w') as handle:  # pylint: disable=unspecified-encoding
            json.dump(safe_summary, handle, indent=2, sort_keys=True)
        LOGGER.info('Run summary written to %s', file_path)
        return file_path
    except Exception:  # pragma: no cover - disk permission issues
        LOGGER.exception('Failed to write summary file: %s', file_path)
        return None


def _sanitize(payload):
    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            if isinstance(key, (str, unicode)):
                sanitized[key] = _sanitize(value)
        return sanitized
    if isinstance(payload, (list, tuple)):
        return [_sanitize(item) for item in payload]
    if isinstance(payload, (str, unicode, bool, int, float)) or payload is None:
        return payload
    return unicode(payload)


def _install_exception_hook():
    if _LOG_STATE.get('previous_hook') is not None:
        return
    previous = sys.excepthook

    def _hook(exc_type, value, tb):  # pragma: no cover - host controlled
        LOGGER.critical('Fatal exception:', exc_info=(exc_type, value, tb))
        if previous and previous is not sys.__excepthook__:
            try:
                previous(exc_type, value, tb)
            except Exception:
                pass

    _LOG_STATE['previous_hook'] = previous
    sys.excepthook = _hook


def _install_qt_message_handler():  # pragma: no cover - only in host with Qt
    if QtCore is None or _LOG_STATE.get('qt_handler_installed'):
        return
    disable_flag = os.environ.get(_QT_DISABLE_ENV, '').strip().lower()
    if disable_flag in ('1', 'true', 'yes', 'on'):
        LOGGER.warning('Qt message handler disabled via %s', _QT_DISABLE_ENV)
        return

    def _qt_handler(msg_type, context, message):
        try:
            level = _qt_level_from_msg(msg_type)
            cache = _LOG_STATE.setdefault('qt_message_cache', {})
            key = unicode(message)
            now = time.time()
            entry = cache.get(key)
            if entry and (now - entry.get('last_time', 0)) > _QT_RESET_SECONDS:
                entry = None
            if entry is None:
                entry = {'count': 0, 'suppressed': 0}
            entry['count'] += 1
            entry['last_time'] = now
            line = getattr(context, 'line', '?')
            func = getattr(context, 'function', '?')
            file_name = getattr(context, 'file', '?')
            if entry['count'] <= _QT_REPEAT_LIMIT:
                LOGGER.log(level, 'Qt: %s (line=%s function=%s file=%s)', message, line, func, file_name)
            else:
                entry['suppressed'] += 1
                if entry['suppressed'] == 1 or not (entry['suppressed'] % _QT_SUPPRESS_INTERVAL):
                    LOGGER.log(
                        level,
                        'Qt message repeated %d times (%d suppressed). Last occurrence: %s (line=%s function=%s file=%s)',
                        entry['count'],
                        entry['suppressed'],
                        message,
                        line,
                        func,
                        file_name,
                    )
            cache[key] = entry
        except Exception:
            LOGGER.exception('Qt message handler failed')

    try:
        QtCore.qInstallMessageHandler(_qt_handler)
        _LOG_STATE['qt_handler_installed'] = True
    except Exception:
        LOGGER.exception('Could not install Qt message handler')


def _qt_level_from_msg(msg_type):
    mapping = {
        0: logging.DEBUG,   # QtDebugMsg
        1: logging.WARNING, # QtWarningMsg
        2: logging.ERROR,   # QtCriticalMsg
        3: logging.CRITICAL,  # QtFatalMsg
        4: logging.INFO,    # QtInfoMsg (Qt >= 5.5)
    }
    try:
        numeric = int(msg_type)
    except Exception:
        return logging.INFO
    return mapping.get(numeric, logging.INFO)


def _ensure_directory(path_value):
    if not path_value:
        return path_value
    if not os.path.exists(path_value):
        try:
            os.makedirs(path_value)
        except OSError:
            pass
    return path_value


def _user_home():
    return os.path.expanduser('~')
