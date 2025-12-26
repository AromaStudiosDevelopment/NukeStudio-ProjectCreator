# -*- coding: utf-8 -*-
"""Background loader thread skeleton."""

from __future__ import absolute_import

import logging
import os

from PySide2 import QtCore  # pylint: disable=import-error

from nuke_kitsu_loader.core import kitsu_client, utils

try:  # pragma: no cover - Hiero only exists inside Nuke Studio
    import hiero.core
except ImportError:  # pragma: no cover
    hiero = None

try:  # pragma: no cover - Python 3 tooling support
    unicode
except NameError:  # pragma: no cover
    unicode = str

LOGGER = logging.getLogger(__name__)


class LoaderThread(QtCore.QThread):
    """Loads plates and scripts without blocking the UI."""

    progress = QtCore.Signal(int)
    message = QtCore.Signal(unicode)  # pylint: disable=undefined-variable
    completed = QtCore.Signal(dict)
    errored = QtCore.Signal(dict)

    def __init__(self, sequences, parent=None):
        super(LoaderThread, self).__init__(parent)
        self._sequences = sequences or []
        self._cancel = False
        self._total_shots = 0
        self._processed_shots = 0
        self._project = None

    def cancel(self):
        """Allow the UI to request cancelation."""
        self._cancel = True

    def run(self):
        """Process all selected sequences, building footage tracks."""
        summary = {
            'sequences': [],
            'errors': [],
            'processed_shots': 0,
        }
        if not self._sequences:
            self.completed.emit(summary)
            return
        plans, prep_errors = self._prepare_sequence_plans()
        summary['errors'].extend(prep_errors)
        if not plans:
            self.completed.emit(summary)
            return
        self._total_shots = sum(len(plan['shots']) for plan in plans) or 1
        for plan in plans:
            if self._cancel:
                self.message.emit('Loader canceled before finishing all sequences')
                break
            sequence_summary = self._process_sequence_plan(plan)
            summary['sequences'].append(sequence_summary)
            summary['errors'].extend(sequence_summary['errors'])
        summary['processed_shots'] = self._processed_shots
        self.completed.emit(summary)

    def _emit_error(self, code, message, shot=None, sequence_name=None):
        payload = {
            'code': code,
            'message': message,
            'shot': shot,
            'sequence': sequence_name,
        }
        LOGGER.error('%s: %s (shot=%s sequence=%s)', code, message, shot, sequence_name)
        self.errored.emit(payload)
        return payload

    def _import_clip_to_footage_bin(self, media_path):
        if hiero is None:
            return False, 'Hiero API is not available outside Nuke Studio.'
        projects = hiero.core.projects()
        if not projects:
            return False, 'No open Hiero project to import into.'
        project = projects[-1]
        self._project = project
        root_bin = project.clipsBin()
        footage_bin = self._find_or_create_bin(root_bin, 'Footage')
        try:
            clip = footage_bin.createClip(media_path)
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.exception('Failed to import %s: %s', media_path, exc)
            return False, str(exc)
        return True, {'clip': clip, 'bin': footage_bin, 'project': project}

    def _find_or_create_bin(self, root_bin, name):
        existing = self._find_bin_by_name(root_bin, name)
        if existing:
            return existing
        new_bin = hiero.core.Bin(name)
        root_bin.addItem(hiero.core.BinItem(new_bin))
        return new_bin

    def _find_bin_by_name(self, root_bin, name):
        for item in root_bin.items():
            active = item.activeItem() if hasattr(item, 'activeItem') else None
            if isinstance(active, hiero.core.Bin) and active.name() == name:
                return active
        return None

    def _prepare_sequence_plans(self):
        plans = []
        errors = []
        for sequence in self._sequences:
            if self._cancel:
                break
            sequence_name = sequence.get('name')
            self.message.emit('Fetching shots for sequence %s' % sequence_name)
            ok, shots = kitsu_client.get_shots_for_sequence(sequence.get('id'))
            if not ok:
                errors.append(self._emit_error('KITSU_ERROR', unicode(shots), sequence_name=sequence_name))
                continue
            if not shots:
                errors.append(self._emit_error('MISSING_SHOTS', 'Sequence has no shots', sequence_name=sequence_name))
                continue
            plans.append({
                'sequence': sequence,
                'shots': shots,
                'task_name': (sequence.get('task') or {}).get('name'),
            })
        return plans, errors

    def _process_sequence_plan(self, plan):
        sequence = plan['sequence']
        sequence_name = sequence.get('name')
        task_name = plan.get('task_name')
        shot_entries = []
        errors = []
        for shot in plan['shots']:
            if self._cancel:
                break
            shot_result = self._process_shot(sequence_name, shot, task_name)
            fatal = shot_result.get('fatal_error')
            if fatal:
                errors.append(fatal)
            else:
                entry = shot_result.get('entry')
                if entry:
                    shot_entries.append(entry)
                errors.extend(shot_result.get('warnings', []))
            self._processed_shots += 1
            self._emit_progress()
        if not shot_entries:
            self.message.emit('No plates imported for sequence %s' % sequence_name)
            return {
                'sequence': sequence_name,
                'shots_requested': len(plan['shots']),
                'shots_imported': 0,
                'errors': errors,
            }
        ok, payload = self._build_sequence_timeline(sequence_name, shot_entries)
        if not ok:
            errors.append(self._emit_error('HIERO_ERROR', unicode(payload), sequence_name=sequence_name))
        else:
            self.message.emit('Created sequence %s with %d clips' % (sequence_name, len(shot_entries)))
        return {
            'sequence': sequence_name,
            'shots_requested': len(plan['shots']),
            'shots_imported': len(shot_entries),
            'errors': errors,
        }

    def _process_shot(self, sequence_name, shot, task_name):
        shot_name = shot.get('name')
        ok, comment = kitsu_client.get_latest_conform_comment(shot.get('id'))
        if not ok:
            return {'fatal_error': self._emit_error('KITSU_ERROR', unicode(comment), shot=shot_name, sequence_name=sequence_name)}
        location = utils.extract_location_from_comment(comment)
        if not location:
            return {'fatal_error': self._emit_error('MISSING_LOCATION', 'No location found in conform comment', shot=shot_name, sequence_name=sequence_name)}
        location = kitsu_client.translate_repo_path_to_unc(location)
        if not utils.path_exists(location):
            return {'fatal_error': self._emit_error('UNREACHABLE_PATH', 'Path not reachable: %s' % location, shot=shot_name, sequence_name=sequence_name)}
        ok, clip_payload = self._import_clip_to_footage_bin(location)
        if not ok:
            return {'fatal_error': self._emit_error('HIERO_ERROR', unicode(clip_payload), shot=shot_name, sequence_name=sequence_name)}
        self.message.emit('Imported plate for shot %s from %s' % (shot_name, location))
        script_path, warning = self._retrieve_script_path(shot, task_name, sequence_name)
        warnings = []
        if warning:
            warnings.append(warning)
        return {
            'entry': {
                'shot': shot_name,
                'clip': clip_payload.get('clip'),
                'path': location,
                'script_path': script_path,
            },
            'warnings': warnings,
        }

    def _retrieve_script_path(self, shot, task_name, sequence_name):
        if not task_name:
            return None, None
        shot_name = shot.get('name')
        ok, result = kitsu_client.get_latest_workfile_for_shot(shot.get('id'), task_name)
        if not ok:
            return None, self._emit_error('KITSU_ERROR', unicode(result), shot=shot_name, sequence_name=sequence_name)
        if not result:
            return None, self._emit_error('MISSING_WORKFILE', 'No %s workfile found' % task_name, shot=shot_name, sequence_name=sequence_name)
        script_path = kitsu_client.translate_repo_path_to_unc(result)
        if not utils.path_exists(script_path):
            return None, self._emit_error('UNREACHABLE_PATH', 'Workfile not reachable: %s' % script_path, shot=shot_name, sequence_name=sequence_name)
        return script_path, None

    def _build_sequence_timeline(self, sequence_name, shot_entries):
        project = self._get_active_project()
        if project is None:
            return False, 'No active Hiero project available.'
        if hiero is None:
            return False, 'Hiero API is not available outside Nuke Studio.'
        try:
            sequence_obj = hiero.core.Sequence(sequence_name)
            try:
                sequence_obj.setFramerate(project.framerate())
            except AttributeError:
                pass
            footage_track = hiero.core.VideoTrack('footage')
            scripts_track = hiero.core.VideoTrack('scripts')
            sequence_obj.addTrack(footage_track)
            sequence_obj.addTrack(scripts_track)
            timeline_in = 0
            for entry in shot_entries:
                clip = entry['clip']
                duration = self._clip_duration(clip)
                track_item = hiero.core.TrackItem('%s_plate' % entry['shot'])
                track_item.setSource(clip)
                track_item.setSourceIn(0)
                track_item.setSourceOut(duration)
                track_item.setTimelineIn(timeline_in)
                track_item.setTimelineOut(timeline_in + duration)
                footage_track.addItem(track_item)
                self._add_script_track_item(scripts_track, clip, entry, timeline_in, timeline_in + duration)
                timeline_in += duration
            project.clipsBin().addItem(hiero.core.BinItem(sequence_obj))
        except Exception as exc:  # pragma: no cover - host specific
            LOGGER.exception('Failed to build sequence %s: %s', sequence_name, exc)
            return False, str(exc)
        return True, {'sequence': sequence_obj}

    def _clip_duration(self, clip):
        for attr in ('duration', 'sourceDuration', 'sourceMediaDuration'):
            if hasattr(clip, attr):
                descriptor = getattr(clip, attr)
                value = descriptor() if callable(descriptor) else descriptor
                if value:
                    return int(value)
        return 1

    def _get_active_project(self):
        if self._project is not None:
            return self._project
        if hiero is None:
            return None
        projects = hiero.core.projects()
        if not projects:
            return None
        self._project = projects[-1]
        return self._project

    def _emit_progress(self):
        percent = int((self._processed_shots / float(self._total_shots)) * 100) if self._total_shots else 100
        self.progress.emit(percent)

    def _add_script_track_item(self, scripts_track, clip, entry, timeline_in, timeline_out):
        script_path = entry.get('script_path')
        if not script_path:
            return
        duration = max(1, timeline_out - timeline_in)
        try:
            script_item = hiero.core.TrackItem('%s_script' % entry['shot'])
            script_item.setSource(clip)
            script_item.setSourceIn(0)
            script_item.setSourceOut(duration)
            script_item.setTimelineIn(timeline_in)
            script_item.setTimelineOut(timeline_out)
            self._label_script_item(script_item, script_path, entry['shot'])
            scripts_track.addItem(script_item)
        except Exception as exc:  # pragma: no cover - host specific
            LOGGER.warning('Failed to add script item for %s: %s', entry['shot'], exc)

    def _label_script_item(self, track_item, script_path, shot_name):
        base_name = os.path.basename(script_path) or script_path
        try:
            track_item.setName('%s_script' % shot_name)
        except Exception:  # pragma: no cover - depends on Hiero
            pass
        note = '%s' % base_name
        try:
            metadata = track_item.metadata()
        except Exception:
            metadata = None
        if metadata is not None:
            try:
                metadata.setValue('kitsu.script_path', script_path)
                metadata.setValue('kitsu.script_label', note)
                track_item.setMetadata(metadata)
                return
            except Exception:
                pass
        for method_name in ('setMetadata', 'addMetadata', 'setTag'):  # best-effort fallbacks
            method = getattr(track_item, method_name, None)
            if not callable(method):
                continue
            try:
                method('kitsu.script_path', script_path)
                return
            except Exception:
                continue
        LOGGER.info('Script path for %s: %s', shot_name, script_path)
