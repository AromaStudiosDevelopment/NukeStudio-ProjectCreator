# -*- coding: utf-8 -*-
"""Background loader thread skeleton."""

from __future__ import absolute_import

import logging
import os

from PySide2 import QtCore  # pylint: disable=import-error

from nuke_kitsu_loader.core import debug, kitsu_client, utils

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
        try:
            self._process_sequences(summary)
        except Exception:  # pragma: no cover - unexpected failure
            crash_details = debug.record_exception('LoaderThread.run')
            message = 'Loader thread crashed; see log %s' % (crash_details.get('log_file') or 'unknown')
            summary['errors'].append(self._emit_error('UNHANDLED_EXCEPTION', message))
            summary['crash'] = crash_details
        finally:
            summary['processed_shots'] = self._processed_shots
            summary['log_file'] = debug.current_log_file()
            summary_path = debug.write_run_summary(summary)
            if summary_path:
                summary['summary_file'] = summary_path
                self.message.emit('Run summary saved to %s' % summary_path)
            self.completed.emit(summary)

    def _process_sequences(self, summary):
        if not self._sequences:
            self.message.emit('No sequences selected for loading')
            return
        plans, prep_errors = self._prepare_sequence_plans()
        summary['errors'].extend(prep_errors)
        if not plans:
            return
        self._total_shots = sum(len(plan['shots']) for plan in plans) or 1
        for plan in plans:
            if self._cancel:
                self.message.emit('Loader canceled before finishing all sequences')
                break
            sequence_summary = self._process_sequence_plan(plan)
            summary['sequences'].append(sequence_summary)
            summary['errors'].extend(sequence_summary['errors'])

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
        project = self._get_active_project()
        if project is None:
            try:
                project = hiero.core.newProject()
                self._project = project
            except Exception as exc:  # pragma: no cover - depends on Hiero environment
                LOGGER.exception('Failed to create Hiero project: %s', exc)
                return False, 'Unable to create Hiero project: %s' % exc
        normalized_path = self._normalize_hiero_path(media_path)
        root_bin = project.clipsBin()
        footage_bin = self._find_or_create_bin(root_bin, 'Footage')
        try:
            imported_result = footage_bin.importFolder(normalized_path)
            LOGGER.debug('Import completed for: %s', normalized_path)
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.exception('Failed to import %s: %s', normalized_path, exc)
            return False, str(exc)
        clip = self._resolve_imported_clip(footage_bin, imported_result)
        if clip is None:
            return False, 'No sequence or clip found in %s after import.' % normalized_path
        return True, {
            'clip': clip,
            'bin': footage_bin,
            'project': project,
            'path': normalized_path,
        }

    def _find_or_create_bin(self, root_bin, name):
        existing = self._find_bin_by_name(root_bin, name)
        if existing is not None:
            return existing
        new_bin = hiero.core.Bin(name)
        try:
            root_bin.addItem(new_bin)
        except Exception:
            root_bin.addItem(hiero.core.BinItem(new_bin))
        return new_bin

    def _find_bin_by_name(self, root_bin, name):
        items = getattr(root_bin, 'items', None)
        if not callable(items):
            return None
        for item in items():
            if isinstance(item, hiero.core.Bin) and item.name() == name:
                return item
            active = item.activeItem() if hasattr(item, 'activeItem') else None
            if isinstance(active, hiero.core.Bin) and active.name() == name:
                return active
        return None

    def _normalize_hiero_path(self, path_value):
        normalized = os.path.normpath(path_value)
        if hiero is not None:
            try:
                normalized = hiero.core.remapPath(normalized)
            except Exception:  # pragma: no cover
                pass
        return normalized

    def _resolve_imported_clip(self, footage_bin, imported_result):
        clip = self._pick_first_source(imported_result)
        if clip is not None:
            return clip
        clip = self._pick_first_source(footage_bin)
        return clip

    def _pick_first_source(self, container):
        if container is None:
            return None
        sequences = getattr(container, 'sequences', None)
        if callable(sequences):
            seq_items = sequences()
            if seq_items:
                seq_item = seq_items[0]
                if hasattr(seq_item, 'activeItem'):
                    try:
                        return seq_item.activeItem()
                    except Exception:
                        pass
        clips = getattr(container, 'clips', None)
        if callable(clips):
            clip_items = clips()
            if clip_items:
                clip_item = clip_items[0]
                if hasattr(clip_item, 'activeItem'):
                    try:
                        return clip_item.activeItem()
                    except Exception:
                        pass
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
                self._add_script_track_item(sequence_name, scripts_track, entry, timeline_in, timeline_in + duration)
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

    def _add_script_track_item(self, sequence_name, scripts_track, entry, timeline_in, timeline_out):
        script_path = entry.get('script_path')
        if not script_path:
            return
        ok, asset = self._import_script_asset(script_path)
        if not ok:
            self._emit_error('HIERO_ERROR', unicode(asset), shot=entry['shot'], sequence_name=sequence_name)
            return
        duration = max(1, timeline_out - timeline_in)
        try:
            script_item = scripts_track.createTrackItem('%s_script' % entry['shot'])
            source = asset.get('clip') or asset.get('placeholder_sequence')
            if source is not None:
                try:
                    script_item.setSource(source)
                    script_item.setSourceIn(0)
                    source_duration = self._clip_duration(source)
                    script_item.setSourceOut(min(source_duration, duration))
                except Exception:
                    pass
            script_item.setTimelineIn(timeline_in)
            script_item.setTimelineOut(timeline_out)
            self._label_script_item(script_item, asset.get('path') or script_path, entry['shot'])
            scripts_track.addItem(script_item)
            self.message.emit('Linked script %s to shot %s' % (asset.get('path') or script_path, entry['shot']))
        except Exception as exc:  # pragma: no cover - host specific
            LOGGER.warning('Failed to add script item for %s: %s', entry['shot'], exc)

    def _import_script_asset(self, script_path):
        if hiero is None:
            return False, 'Hiero API is not available outside Nuke Studio.'
        project = self._get_active_project()
        if project is None:
            try:
                project = hiero.core.newProject()
                self._project = project
            except Exception as exc:  # pragma: no cover
                LOGGER.exception('Failed to create Hiero project for scripts: %s', exc)
                return False, 'Unable to create Hiero project: %s' % exc
        normalized_path = self._normalize_hiero_path(script_path)
        scripts_bin = self._find_or_create_bin(project.clipsBin(), 'Scripts')
        try:
            clip_obj = hiero.core.Clip(normalized_path)
            bin_item = hiero.core.BinItem(clip_obj)
            scripts_bin.addItem(bin_item)
            return True, {
                'clip': clip_obj,
                'bin_item': bin_item,
                'path': normalized_path,
            }
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.debug('Could not create clip from %s: %s', normalized_path, exc)
            placeholder_name = os.path.basename(normalized_path) or 'workfile'
            placeholder_seq = hiero.core.Sequence(placeholder_name)
            bin_item = hiero.core.BinItem(placeholder_seq)
            scripts_bin.addItem(bin_item)
            return True, {
                'clip': None,
                'placeholder_sequence': placeholder_seq,
                'bin_item': bin_item,
                'path': normalized_path,
            }

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
