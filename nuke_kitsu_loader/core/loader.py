# -*- coding: utf-8 -*-
"""Background loader thread skeleton."""

from __future__ import absolute_import

import logging
import os

from PySide2 import QtCore  # pylint: disable=import-error

from nuke_kitsu_loader.core import debug, kitsu_client, utils

try:  # pragma: no cover - Hiero only exists inside Nuke Studio
    import hiero.core
    import hiero
except ImportError:  # pragma: no cover
    hiero = None

try:  # pragma: no cover - Python 3 tooling support
    unicode
except NameError:  # pragma: no cover
    unicode = str

LOGGER = logging.getLogger(__name__)


class MainThreadExecutor(QtCore.QObject):
    """Helper to execute Hiero operations on the main thread from worker threads."""

    execute_requested = QtCore.Signal(object, object)  # callable, args_tuple
    execution_complete = QtCore.Signal()

    def __init__(self):
        super(MainThreadExecutor, self).__init__()
        self._result = None
        self._exception = None
        self._mutex = QtCore.QMutex()
        self._wait_condition = QtCore.QWaitCondition()
        self.execute_requested.connect(self._do_execute)

    @QtCore.Slot(object, object)
    def _do_execute(self, callable_obj, args_tuple):
        """Execute any callable on main thread with args."""
        self._mutex.lock()
        try:
            self._result = callable_obj(*args_tuple)
            self._exception = None
        except Exception as exc:
            self._exception = exc
            self._result = None
        finally:
            self._wait_condition.wakeAll()
            self._mutex.unlock()

    def execute_on_main_thread(self, callable_obj, args_tuple):
        """Execute callable on main thread and wait for result."""
        self._mutex.lock()
        try:
            self._result = None
            self._exception = None
            self.execute_requested.emit(callable_obj, args_tuple)
            self._wait_condition.wait(self._mutex)
            result = self._result
            exception = self._exception
            self._result = None
            self._exception = None
            if exception:
                raise exception
            return result
        finally:
            self._mutex.unlock()


class LoaderThread(QtCore.QThread):
    """Loads plates and scripts without blocking the UI."""

    progress = QtCore.Signal(int)
    message = QtCore.Signal(unicode)  # pylint: disable=undefined-variable
    completed = QtCore.Signal(dict)
    errored = QtCore.Signal(dict)

    def __init__(self, sequences, project_name=None, main_thread_executor=None, parent=None):
        super(LoaderThread, self).__init__(parent)
        self._sequences = sequences or []
        self._project_name = project_name or 'Timeline'
        self._cancel = False
        self._total_shots = 0
        self._processed_shots = 0
        self._project = None
        self._main_thread_executor = main_thread_executor

    def cancel(self):
        """Allow the UI to request cancelation."""
        self._cancel = True

    def _invoke_on_main_thread(self, callable_obj, *args):
        """Execute a callable on the main thread and return the result."""
        if self._main_thread_executor is None:
            raise RuntimeError('MainThreadExecutor not provided to LoaderThread')
        return self._main_thread_executor.execute_on_main_thread(callable_obj, args)

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
        
        # Collect all shot entries from all sequences
        all_shot_entries = []
        all_task_names = set()
        all_errors = []
        
        for plan in plans:
            if self._cancel:
                self.message.emit('Loader canceled before finishing all sequences')
                break
            sequence_summary = self._process_sequence_plan_for_combined_timeline(plan, all_shot_entries, all_task_names, all_errors)
            summary['sequences'].append(sequence_summary)
        
        summary['errors'].extend(all_errors)
        
        # Build one combined timeline with all sequences
        if all_shot_entries and not self._cancel:
            ok, payload = self._build_sequence_timeline(self._project_name, all_shot_entries, list(all_task_names))
            if not ok:
                all_errors.append(self._emit_error('HIERO_ERROR', unicode(payload), sequence_name=self._project_name))
            else:
                self.message.emit('Created timeline %s with %d clips from %d sequences' % (self._project_name, len(all_shot_entries), len(plans)))

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
        LOGGER.info('Starting clip import for: %s', media_path)
        project = self._get_active_project()
        if project is None:
            LOGGER.info('No active project found; creating new project')
            try:
                project = self._invoke_on_main_thread(lambda: hiero.core.newProject())
                self._project = project
                LOGGER.info('Created new Hiero project')
            except Exception as exc:  # pragma: no cover - depends on Hiero environment
                LOGGER.exception('Failed to create Hiero project: %s', exc)
                return False, 'Unable to create Hiero project: %s' % exc
        normalized_path = self._normalize_hiero_path(media_path)
        LOGGER.info('Normalized path: %s', normalized_path)
        try:
            root_bin = self._invoke_on_main_thread(lambda: project.clipsBin())
            LOGGER.debug('Got project clips bin')
        except Exception as exc:
            LOGGER.exception('Failed to access project clips bin: %s', exc)
            return False, 'Cannot access project clips bin: %s' % exc
        footage_bin = self._find_or_create_bin(root_bin, 'Footage')
        if footage_bin is None:
            return False, 'Failed to create or find Footage bin'
        LOGGER.info('Using Footage bin: %s', footage_bin.name())
        try:
            LOGGER.info('Calling importFolder on path: %s', normalized_path)
            imported_result = self._invoke_on_main_thread(lambda: footage_bin.importFolder(normalized_path))
            LOGGER.info('importFolder completed, result type: %s', type(imported_result).__name__)
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.exception('Failed to import %s: %s', normalized_path, exc)
            return False, 'Import failed: %s' % str(exc)
        clip = self._resolve_imported_clip(footage_bin, imported_result)
        if clip is None:
            LOGGER.error('No clip/sequence found after import in bin or result')
            return False, 'No sequence or clip found in %s after import.' % normalized_path
        LOGGER.info('Successfully resolved clip: %s (type: %s)', getattr(clip, 'name', lambda: 'unknown')(), type(clip).__name__)
        return True, {
            'clip': clip,
            'bin': footage_bin,
            'project': project,
            'path': normalized_path,
        }

    def _import_clip_to_render_bin(self, media_path):
        """Import render clip to Render bin (similar to footage import)."""
        if hiero is None:
            return False, 'Hiero API is not available outside Nuke Studio.'
        LOGGER.info('Starting render import for: %s', media_path)
        project = self._get_active_project()
        if project is None:
            LOGGER.info('No active project found; creating new project')
            try:
                project = self._invoke_on_main_thread(lambda: hiero.core.newProject())
                self._project = project
                LOGGER.info('Created new Hiero project')
            except Exception as exc:  # pragma: no cover - depends on Hiero environment
                LOGGER.exception('Failed to create Hiero project: %s', exc)
                return False, 'Unable to create Hiero project: %s' % exc
        normalized_path = self._normalize_hiero_path(media_path)
        LOGGER.info('Normalized render path: %s', normalized_path)
        try:
            root_bin = self._invoke_on_main_thread(lambda: project.clipsBin())
            LOGGER.debug('Got project clips bin')
        except Exception as exc:
            LOGGER.exception('Failed to access project clips bin: %s', exc)
            return False, 'Cannot access project clips bin: %s' % exc
        render_bin = self._find_or_create_bin(root_bin, 'Render')
        if render_bin is None:
            return False, 'Failed to create or find Render bin'
        LOGGER.info('Using Render bin: %s', render_bin.name())
        try:
            LOGGER.info('Calling importFolder on render path: %s', normalized_path)
            imported_result = self._invoke_on_main_thread(lambda: render_bin.importFolder(normalized_path))
            LOGGER.info('importFolder completed for render, result type: %s', type(imported_result).__name__)
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.exception('Failed to import render %s: %s', normalized_path, exc)
            return False, 'Import failed: %s' % str(exc)
        clip = self._resolve_imported_clip(render_bin, imported_result)
        if clip is None:
            LOGGER.error('No render clip/sequence found after import in bin or result')
            return False, 'No sequence or clip found in %s after import.' % normalized_path
        LOGGER.info('Successfully resolved render clip: %s (type: %s)', getattr(clip, 'name', lambda: 'unknown')(), type(clip).__name__)
        return True, {
            'clip': clip,
            'bin': render_bin,
            'project': project,
            'path': normalized_path,
        }

    def _find_or_create_bin(self, root_bin, name):
        LOGGER.debug('Finding or creating bin: %s', name)
        try:
            items = self._invoke_on_main_thread(lambda: root_bin.items())
            for item in items:
                if isinstance(item, hiero.core.Bin) and item.name() == name:
                    LOGGER.debug('Found existing bin (direct): %s', name)
                    return item
        except Exception as exc:
            LOGGER.warning('Could not iterate bin items: %s', exc)
        LOGGER.debug('Creating new bin: %s', name)
        try:
            def create_bin():
                new_bin = hiero.core.Bin(name)
                root_bin.addItem(new_bin)
                return new_bin
            new_bin = self._invoke_on_main_thread(create_bin)
            LOGGER.info('Created bin %s and added to root', name)
            return new_bin
        except Exception as exc:
            LOGGER.exception('Failed to create/add bin %s: %s', name, exc)
            return None

    def _normalize_hiero_path(self, path_value):
        # Use forward slashes instead of backslashes
        normalized = path_value.replace('\\', '/')
        if hiero is not None:
            try:
                normalized = hiero.core.remapPath(normalized)
                # Ensure forward slashes after remapPath
                normalized = normalized.replace('\\', '/')
            except Exception:  # pragma: no cover
                pass
        return normalized

    def _resolve_imported_clip(self, footage_bin, imported_result):
        LOGGER.debug('Resolving imported clip from bin and result')
        try:
            sequence_binitems = footage_bin.sequences()
            if sequence_binitems:
                # Get the LAST (most recently imported) sequence, not the first
                source_obj = sequence_binitems[-1].activeItem()
                LOGGER.info('Found imported Sequence: %s', sequence_binitems[-1].name())
                return source_obj
        except Exception as exc:
            LOGGER.debug('No sequences in footage_bin or error: %s', exc)
        try:
            clip_binitems = footage_bin.clips()
            if clip_binitems:
                # Get the LAST (most recently imported) clip, not the first
                source_obj = clip_binitems[-1].activeItem()
                LOGGER.info('Found imported Clip: %s', clip_binitems[-1].name())
                return source_obj
        except Exception as exc:
            LOGGER.debug('No clips in footage_bin or error: %s', exc)
        if isinstance(imported_result, hiero.core.Bin) and imported_result is not footage_bin:
            LOGGER.debug('Checking separate imported_result bin')
            try:
                seqs = imported_result.sequences()
                if seqs:
                    # Get the LAST sequence
                    source_obj = seqs[-1].activeItem()
                    LOGGER.info('Found Sequence in imported_result bin: %s', seqs[-1].name())
                    return source_obj
            except Exception as exc:
                LOGGER.debug('No sequences in imported_result: %s', exc)
            try:
                clips = imported_result.clips()
                if clips:
                    # Get the LAST clip
                    source_obj = clips[-1].activeItem()
                    LOGGER.info('Found Clip in imported_result bin: %s', clips[-1].name())
                    return source_obj
            except Exception as exc:
                LOGGER.debug('No clips in imported_result: %s', exc)
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
                'task_names': sequence.get('tasks', []),  # List of task names
            })
        return plans, errors

    def _process_sequence_plan_for_combined_timeline(self, plan, all_shot_entries, all_task_names, all_errors):
        """Process a sequence and add its shots to the combined timeline."""
        sequence = plan['sequence']
        sequence_name = sequence.get('name')
        task_names = plan.get('task_names', [])
        all_task_names.update(task_names)
        shot_entries = []
        errors = []
        
        # Process all shots for plates (from Conforming task)
        for shot in plan['shots']:
            if self._cancel:
                break
            shot_result = self._process_shot_plate(sequence_name, shot)
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
        
        # For each selected task, fetch workfiles and renders for all shots
        for task_name in task_names:
            for entry in shot_entries:
                if self._cancel:
                    break
                shot_name = entry['shot']
                # Find the original shot dict
                shot = next((s for s in plan['shots'] if s.get('name') == shot_name), None)
                if not shot:
                    continue
                
                # Get workfile path
                script_path, warning = self._retrieve_script_path(shot, task_name, sequence_name)
                if warning:
                    errors.append(warning)
                # Add workfile paths to entry, keyed by task name
                if 'workfiles' not in entry:
                    entry['workfiles'] = {}
                entry['workfiles'][task_name] = script_path
                
                # Get render path and import it
                render_result = self._retrieve_render_path(shot, task_name, sequence_name)
                if render_result.get('error'):
                    errors.append(render_result['error'])
                # Add render info to entry, keyed by task name
                if 'renders' not in entry:
                    entry['renders'] = {}
                entry['renders'][task_name] = render_result.get('render_info')
        
        # Add this sequence's shots to the combined list
        all_shot_entries.extend(shot_entries)
        all_errors.extend(errors)
        
        return {
            'sequence': sequence_name,
            'shots_requested': len(plan['shots']),
            'shots_imported': len(shot_entries),
            'errors': errors,
        }

    def _process_sequence_plan(self, plan):
        sequence = plan['sequence']
        sequence_name = sequence.get('name')
        task_names = plan.get('task_names', [])
        shot_entries = []
        errors = []
        
        # Process all shots for plates (from Conforming task)
        for shot in plan['shots']:
            if self._cancel:
                break
            shot_result = self._process_shot_plate(sequence_name, shot)
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
        
        # For each selected task, fetch workfiles and renders for all shots
        for task_name in task_names:
            for entry in shot_entries:
                if self._cancel:
                    break
                shot_name = entry['shot']
                # Find the original shot dict
                shot = next((s for s in plan['shots'] if s.get('name') == shot_name), None)
                if not shot:
                    continue
                
                # Get workfile path
                script_path, warning = self._retrieve_script_path(shot, task_name, sequence_name)
                if warning:
                    errors.append(warning)
                # Add workfile paths to entry, keyed by task name
                if 'workfiles' not in entry:
                    entry['workfiles'] = {}
                entry['workfiles'][task_name] = script_path
                
                # Get render path
                render_result = self._retrieve_render_path(shot, task_name, sequence_name)
                if render_result.get('error'):
                    errors.append(render_result['error'])
                # Add render paths to entry, keyed by task name
                if 'renders' not in entry:
                    entry['renders'] = {}
                entry['renders'][task_name] = render_result.get('render_info')
        
        if not shot_entries:
            self.message.emit('No plates imported for sequence %s' % sequence_name)
            return {
                'sequence': sequence_name,
                'shots_requested': len(plan['shots']),
                'shots_imported': 0,
                'errors': errors,
            }
        ok, payload = self._build_sequence_timeline(sequence_name, shot_entries, task_names)
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

    def _process_shot_plate(self, sequence_name, shot):
        """Process a single shot to import its plate from Conforming task."""
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
        return {
            'entry': {
                'shot': shot_name,
                'shot_id': shot.get('id'),
                'clip': clip_payload.get('clip'),
                'path': location,
            },
            'warnings': [],
        }

    def _retrieve_script_path(self, shot, task_name, sequence_name):
        if not task_name:
            return None, None
        shot_name = shot.get('name')
        ok, result = kitsu_client.get_latest_workfile_for_shot(shot.get('id'), task_name)
        if not ok:
            return None, self._emit_error('KITSU_ERROR', unicode(result), shot=shot_name, sequence_name=sequence_name)
        if not result:
            LOGGER.debug('No %s workfile found for shot %s', task_name, shot_name)
            return None, None  # Not an error, just no workfile yet
        script_path = kitsu_client.translate_repo_path_to_unc(result)
        # Don't validate path existence - let Hiero import handle it with fallback to placeholder
        LOGGER.debug('Found workfile for %s task: %s', task_name, script_path)
        return script_path, None

    def _retrieve_render_path(self, shot, task_name, sequence_name):
        """Retrieve render location from task comments and import the clip."""
        if not task_name:
            return {'render_info': None}
        shot_name = shot.get('name')
        ok, result = kitsu_client.get_latest_render_for_shot(shot.get('id'), task_name)
        if not ok:
            return {'error': self._emit_error('KITSU_ERROR', unicode(result), shot=shot_name, sequence_name=sequence_name)}
        if not result:
            LOGGER.debug('No %s render found for shot %s', task_name, shot_name)
            return {'render_info': None}  # Not an error, just no render yet
        
        render_path = kitsu_client.translate_repo_path_to_unc(result)
        if not utils.path_exists(render_path):
            return {'error': self._emit_error('UNREACHABLE_PATH', 'Render path not reachable: %s' % render_path, shot=shot_name, sequence_name=sequence_name)}
        
        # Import render clip to Render bin
        ok, clip_payload = self._import_clip_to_render_bin(render_path)
        if not ok:
            return {'error': self._emit_error('HIERO_ERROR', unicode(clip_payload), shot=shot_name, sequence_name=sequence_name)}
        
        self.message.emit('Imported render for shot %s from %s' % (shot_name, render_path))
        return {
            'render_info': {
                'clip': clip_payload.get('clip'),
                'path': render_path,
            }
        }

    def _build_sequence_timeline(self, sequence_name, shot_entries, task_names):
        project = self._get_active_project()
        if project is None:
            return False, 'No active Hiero project available.'
        if hiero is None:
            return False, 'Hiero API is not available outside Nuke Studio.'
        LOGGER.info('Building timeline sequence: %s with %d shots and tasks: %s', sequence_name, len(shot_entries), task_names)
        try:
            LOGGER.debug('Creating Sequence object: %s', sequence_name)
            sequence_obj = self._invoke_on_main_thread(lambda: hiero.core.Sequence(sequence_name))
            try:
                framerate = self._invoke_on_main_thread(lambda: project.framerate())
                self._invoke_on_main_thread(lambda: sequence_obj.setFramerate(framerate))
                LOGGER.debug('Set sequence framerate to %s', framerate)
            except Exception as exc:
                LOGGER.debug('Could not set framerate: %s', exc)
            
            # Create footage track
            LOGGER.debug('Creating footage track')
            footage_track = self._invoke_on_main_thread(lambda: hiero.core.VideoTrack('footage'))
            self._invoke_on_main_thread(lambda: sequence_obj.addTrack(footage_track))
            
            # Create comp track and render track for each selected task
            comp_tracks = {}
            render_tracks = {}
            for task_name in task_names:
                LOGGER.debug('Creating comp track for task: %s', task_name)
                comp_track = self._invoke_on_main_thread(lambda tn=task_name: hiero.core.VideoTrack(tn))
                self._invoke_on_main_thread(lambda ct=comp_track: sequence_obj.addTrack(ct))
                comp_tracks[task_name] = comp_track
                
                LOGGER.debug('Creating render track for task: %s', task_name)
                render_track_name = '%s_render' % task_name
                render_track = self._invoke_on_main_thread(lambda rtn=render_track_name: hiero.core.VideoTrack(rtn))
                self._invoke_on_main_thread(lambda rt=render_track: sequence_obj.addTrack(rt))
                render_tracks[task_name] = render_track
            
            timeline_in = 0
            for idx, entry in enumerate(shot_entries):
                LOGGER.debug('Processing shot entry %d/%d: %s', idx + 1, len(shot_entries), entry.get('shot'))
                clip = entry['clip']
                if clip is None:
                    LOGGER.warning('Clip is None for shot %s, skipping', entry.get('shot'))
                    continue
                duration = self._clip_duration(clip)
                LOGGER.debug('Shot %s duration: %d frames', entry.get('shot'), duration)
                
                # Add plate to footage track
                try:
                    def create_and_add_footage_item():
                        track_item = footage_track.createTrackItem('%s_plate' % entry['shot'])
                        track_item.setSource(clip)
                        track_item.setTimelineIn(timeline_in)
                        track_item.setTimelineOut(timeline_in + duration - 1)
                        footage_track.addItem(track_item)
                        return track_item
                    self._invoke_on_main_thread(create_and_add_footage_item)
                    LOGGER.debug('Added footage track item for %s at timeline %d-%d', entry['shot'], timeline_in, timeline_in + duration - 1)
                except Exception as exc:
                    LOGGER.exception('Failed to create footage track item for %s: %s', entry.get('shot'), exc)
                    continue
                
                # Add workfile for each selected task to corresponding comp track
                workfiles = entry.get('workfiles', {})
                renders = entry.get('renders', {})
                for task_name in task_names:
                    # Add script/workfile to comp track
                    script_path = workfiles.get(task_name)
                    if script_path:
                        comp_track = comp_tracks.get(task_name)
                        if comp_track:
                            self._add_script_track_item(sequence_name, comp_track, entry, script_path, timeline_in, timeline_in + duration - 1)
                    
                    # Add render to render track
                    render_info = renders.get(task_name)
                    if render_info and render_info.get('clip'):
                        render_track = render_tracks.get(task_name)
                        if render_track:
                            self._add_render_track_item(sequence_name, render_track, entry, render_info, timeline_in, timeline_in + duration - 1)
                
                timeline_in += duration
                
            LOGGER.info('Adding sequence to project clips bin')
            self._invoke_on_main_thread(lambda: project.clipsBin().addItem(hiero.core.BinItem(sequence_obj)))
            LOGGER.info('Successfully created sequence %s', sequence_name)
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
        projects = self._invoke_on_main_thread(lambda: hiero.core.projects())
        if not projects:
            return None
        self._project = projects[-1]
        return self._project

    def _emit_progress(self):
        percent = int((self._processed_shots / float(self._total_shots)) * 100) if self._total_shots else 100
        self.progress.emit(percent)

    def _add_script_track_item(self, sequence_name, scripts_track, entry, script_path, timeline_in, timeline_out):
        if not script_path:
            LOGGER.debug('No script path for shot %s', entry.get('shot'))
            return
        LOGGER.debug('Adding script track item for shot %s, path: %s', entry.get('shot'), script_path)
        ok, asset = self._import_script_asset(script_path)
        if not ok:
            LOGGER.warning('Script asset import failed for %s: %s', entry.get('shot'), asset)
            self._emit_error('HIERO_ERROR', unicode(asset), shot=entry['shot'], sequence_name=sequence_name)
            return
        try:
            def create_and_add_script_item():
                script_item = scripts_track.createTrackItem('%s_script' % entry['shot'])
                source = asset.get('clip') or asset.get('placeholder_sequence')
                if source is not None:
                    try:
                        script_item.setSource(source)
                        LOGGER.debug('Set script track item source for %s', entry['shot'])
                    except Exception as exc:
                        LOGGER.debug('Could not set script source: %s', exc)
                script_item.setTimelineIn(timeline_in)
                script_item.setTimelineOut(timeline_out)
                self._label_script_item(script_item, asset.get('path') or script_path, entry['shot'])
                scripts_track.addItem(script_item)
                return script_item
            self._invoke_on_main_thread(create_and_add_script_item)
            LOGGER.info('Added script track item for shot %s', entry['shot'])
            self.message.emit('Linked script %s to shot %s' % (os.path.basename(asset.get('path') or script_path), entry['shot']))
        except Exception as exc:  # pragma: no cover - host specific
            LOGGER.exception('Failed to add script track item for %s: %s', entry['shot'], exc)
            self._emit_error('HIERO_ERROR', unicode(exc), shot=entry['shot'], sequence_name=sequence_name)

    def _import_script_asset(self, script_path):
        LOGGER.debug('Importing script asset: %s', script_path)
        project = self._get_active_project()
        if project is None:
            LOGGER.debug('Creating project for scripts')
            try:
                project = hiero.core.newProject()
                self._project = project
            except Exception as exc:  # pragma: no cover
                LOGGER.exception('Failed to create Hiero project for scripts: %s', exc)
                return False, 'Unable to create Hiero project: %s' % exc
        normalized_path = self._normalize_hiero_path(script_path)
        LOGGER.debug('Normalized script path: %s', normalized_path)
        scripts_bin = self._find_or_create_bin(self._invoke_on_main_thread(lambda: project.clipsBin()), 'Scripts')
        if scripts_bin is None:
            return False, 'Could not create Scripts bin'
        try:
            LOGGER.debug('Attempting to create Clip from script path')
            def create_clip_and_add():
                clip_obj = hiero.core.Clip(normalized_path)
                bin_item = hiero.core.BinItem(clip_obj)
                scripts_bin.addItem(bin_item)
                return clip_obj, bin_item
            clip_obj, bin_item = self._invoke_on_main_thread(create_clip_and_add)
            LOGGER.info('Created Clip for script: %s', os.path.basename(normalized_path))
            return True, {
                'clip': clip_obj,
                'bin_item': bin_item,
                'path': normalized_path,
            }
        except Exception as exc:  # pragma: no cover - depends on Hiero environment
            LOGGER.debug('Could not create clip from %s (expected for .nk): %s', normalized_path, exc)
            placeholder_name = os.path.basename(normalized_path) or 'workfile'
            try:
                def create_placeholder_and_add():
                    placeholder_seq = hiero.core.Sequence(placeholder_name)
                    bin_item = hiero.core.BinItem(placeholder_seq)
                    scripts_bin.addItem(bin_item)
                    return placeholder_seq, bin_item
                placeholder_seq, bin_item = self._invoke_on_main_thread(create_placeholder_and_add)
                LOGGER.info('Created placeholder sequence for script: %s', placeholder_name)
                return True, {
                    'clip': None,
                    'placeholder_sequence': placeholder_seq,
                    'bin_item': bin_item,
                    'path': normalized_path,
                }
            except Exception as exc2:
                LOGGER.exception('Failed to create placeholder for script %s: %s', placeholder_name, exc2)
                return False, 'Cannot create script placeholder: %s' % str(exc2)

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

    def _add_render_track_item(self, sequence_name, render_track, entry, render_info, timeline_in, timeline_out):
        """Add a render clip as a track item to the render track."""
        render_clip = render_info.get('clip')
        render_path = render_info.get('path')
        if not render_clip:
            LOGGER.debug('No render clip for shot %s', entry.get('shot'))
            return
        LOGGER.debug('Adding render track item for shot %s, path: %s', entry.get('shot'), render_path)
        try:
            def create_and_add_render_item():
                render_item = render_track.createTrackItem('%s_render' % entry['shot'])
                try:
                    render_item.setSource(render_clip)
                    LOGGER.debug('Set render track item source for %s', entry['shot'])
                except Exception as exc:
                    LOGGER.debug('Could not set render source: %s', exc)
                render_item.setTimelineIn(timeline_in)
                render_item.setTimelineOut(timeline_out)
                # Add metadata
                try:
                    metadata = render_item.metadata()
                    if metadata:
                        metadata.setValue('kitsu.render_path', render_path)
                        render_item.setMetadata(metadata)
                except Exception as exc:
                    LOGGER.debug('Could not set render metadata: %s', exc)
                render_track.addItem(render_item)
                return render_item
            self._invoke_on_main_thread(create_and_add_render_item)
            LOGGER.info('Added render track item for shot %s', entry['shot'])
            self.message.emit('Linked render %s to shot %s' % (os.path.basename(render_path or 'render'), entry['shot']))
        except Exception as exc:  # pragma: no cover - host specific
            LOGGER.exception('Failed to add render track item for %s: %s', entry['shot'], exc)
            self._emit_error('HIERO_ERROR', unicode(exc), shot=entry['shot'], sequence_name=sequence_name)
