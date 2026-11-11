"""Application PG logical archive files, authorized staging, publication and recovery."""
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.errors import StorageConfigurationError, UnknownCommitError
from hermes_cli.kanban_storage_owner import BoardFiles, _path, canonical_path
from hermes_cli import kanban_storage_files as files
from hermes_db.domains.kanban.postgres import transfer as db
logger = logging.getLogger('hermes_cli.kanban_storage_transfer')



def copy_registered_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as reader, target.open('xb') as writer:
        shutil.copyfileobj(reader, writer)
    digest = hashlib.sha256()
    with target.open('rb') as copied:
        for chunk in iter(lambda: copied.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'size': target.stat().st_size, 'sha256': digest.hexdigest()}


def _attachments(tables, root, staged, include):
    from hermes_cli.kanban_transfer_values import reanchor_tables
    proofs = {}
    if not include:
        omitted = len(tables['task_attachments'])
        tables['task_attachments'] = []
        return (proofs, [f'{omitted} attachment record(s) omitted by request'] if omitted else [])
    root = root.resolve()
    mapping = {}
    for row in tables['task_attachments']:
        source = Path(row['stored_path']).resolve(strict=True)
        if not source.is_relative_to(root) or source == root:
            raise ValueError('Attachment is outside the managed Board root; retain it or explicitly export without attachments')
        member = 'attachments/' + source.relative_to(root).as_posix()
        if member not in proofs:
            proofs[member] = copy_registered_file(source, staged / member)
        mapping[row['stored_path']] = member
        row['stored_path'] = member
    reanchor_tables(tables, mapping)
    return (proofs, [])


def export_board(board, output_path, *, include_attachments=True, include_logs=False):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_cli.archive_safe import copy_regular_files, make_targz
    from hermes_cli.kanban_transfer import ARCHIVE_FORMAT, _write_json
    from hermes_cli.version_info import get_version_info
    slug = _storage_shared_1._normalize_board_slug(board) or kb.get_current_board()
    base = str(Path(output_path).expanduser()).removesuffix('.tar.gz').removesuffix('.tgz')
    Path(base).parent.mkdir(parents=True, exist_ok=True)
    with kbc.connect_closing(board=slug) as store:
        tables = db.snapshot(store)
        frame = BoardFiles(store.scope.profile_home, store.board_id, store.slug)
    db.scrub_runtime(tables)
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary) / slug
        staged.mkdir()
        proofs, warnings = _attachments(tables, _path(frame, 'HERMES_KANBAN_ATTACHMENTS_ROOT', 'attachments'), staged, include_attachments)
        metadata = kb.read_board_metadata(slug)
        metadata.pop('db_path', None)
        metadata.update(default_workdir=None, project_id=None)
        _write_json(staged / 'board.json', metadata)
        _write_json(staged / 'data.json', {'format_version': db.FORMAT_VERSION, 'tables': tables})
        logs = copy_regular_files(_path(frame, None, 'logs'), staged / 'logs') if include_logs else 0
        manifest = dict(format=ARCHIVE_FORMAT, format_version=db.FORMAT_VERSION, backend='postgresql', board=slug, board_name=metadata.get('name') or slug, exported_at=int(time.time()), hermes_version=get_version_info().base_version, includes={'attachments': bool(include_attachments), 'logs': bool(include_logs)}, files=proofs, counts={**{name: len(rows) for name, rows in tables.items()}, 'attachment_files': len(proofs), 'log_files': logs})
        _write_json(staged / 'manifest.json', manifest)
        archive = make_targz(base, temporary, slug)
    return dict(board=slug, archive=archive, size=Path(archive).stat().st_size, counts=manifest['counts'], warnings=warnings)


def compensate_stage(stage, root, primary):
    from hermes_cli.kanban_storage_files import _remove_directory
    try:
        _remove_directory(stage, parent=root)
    except (OSError, StorageConfigurationError) as error:
        primary.add_note(f'Private import stage cleanup failed ({type(error).__name__}); retain the original stage for reconciliation')


def _prepare_rows(tables, fields):
    from hermes_cli.kanban_transfer_values import reanchor_tables
    db.scrub_runtime(tables)
    parked = set()
    for task in tables['tasks']:
        if task['workspace_kind'] in {'dir', 'worktree'} and task['status'] in {'ready', 'running', 'todo', 'scheduled'}:
            task['status'] = 'triage'
            parked.add(task['id'])
    mapping = {}
    for row in tables['task_attachments']:
        original = row['stored_path']
        member = row['stored_path'].removeprefix('attachments/')
        row['stored_path'] = str(Path(fields['attachments_root']).joinpath(*member.split('/')))
        row['path_key'] = canonical_path(row['stored_path'])
        mapping[original] = row['stored_path']
    reanchor_tables(tables, mapping)
    return parked


def _stage(extracted, resource, board_id):
    from hermes_cli.archive_safe import copy_regular_files
    from hermes_db.core.values import resource_key
    from utils import atomic_json_write
    home = resource.scope.profile_home
    root = home / 'kanban' / 'imports'
    if root.resolve() != home.resolve() / 'kanban' / 'imports':
        raise StorageConfigurationError('Board import staging root is redirected')
    root.mkdir(parents=True, exist_ok=True)
    stage = root / board_id
    stage.mkdir(mode=448)
    try:
        atomic_json_write(stage / '.owner.json', {'store_id': resource.scope.require_store_id(), 'home': str(home), 'target': resource_key(resource._transactions)}, mode=384)
        for name in ('manifest.json', 'board.json', 'data.json'):
            shutil.copyfile(extracted / name, stage / name)
        for name in ('attachments', 'logs'):
            copy_regular_files(extracted / name, stage / name)
        return stage
    except BaseException as primary:
        compensate_stage(stage, root, primary)
        raise


def _import(extracted, requested, *, activate):
    from hermes_cli import kanban_db as kb
    from hermes_cli.db_domains import acquire_profile_domain
    manifest, tables, metadata = read_archive(extracted)
    requested = _storage_shared_1._normalize_board_slug(requested or manifest.get('board') or extracted.name)
    if not requested:
        raise ValueError('Pass an explicit Board slug for this archive')
    with acquire_profile_domain('kanban_tasks') as resource:
        board_id = uuid4().hex
        fields = files.prepare(resource, {'board_id': board_id, 'slug': requested})
        parked = _prepare_rows(tables, fields)
        with files.local_files_lock(resource.scope.profile_home):
            stage = _stage(extracted, resource, board_id)
            try:
                target = db._commit_graph(resource, requested, board_id, stage, tables, fields, parked)
            except UnknownCommitError as error:
                error.add_note(f'Board import {board_id} may be committed; retain its original stage and inspect the file job')
                raise
            except BaseException as primary:
                compensate_stage(stage, resource.scope.profile_home / 'kanban' / 'imports', primary)
                raise
        result = files.run_job(resource, board_id)
    if activate:
        kb.set_current_board(target)
    warnings = [f'{len(parked)} task(s) moved to triage — configure their directory or worktree on this machine'] if parked else []
    if result.get('stage_cleanup_pending'):
        warnings.append('The Board is active; private import-stage cleanup is pending')
    counts = {name: len(rows) for name, rows in tables.items()}
    counts['task_events'] += len(tables['tasks'])
    return dict(board=target, requested_board=requested, renamed=target != requested, name=metadata.get('name') or target, path=str(kb.board_dir(target)), db_path=None, backend='postgresql', board_id=board_id, source={name: manifest.get(name) for name in ('board', 'exported_at', 'hermes_version')}, counts=counts, attachments_restored=len(tables['task_attachments']), tasks_parked=len(parked), warnings=warnings, activated=bool(activate))


def import_board(archive_path, slug=None, *, activate=False):
    from hermes_cli.archive_safe import archive_root_dirs, safe_extract_targz
    archive = Path(archive_path).expanduser()
    roots = archive_root_dirs(archive)
    if len(roots) != 1:
        raise ValueError('A Board archive must contain exactly one top-level directory')
    root = roots.pop()
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        safe_extract_targz(archive, staging)
        return _import(staging / root, slug, activate=activate)


def _publish(source, target, board_id, proofs):
    if not source.is_dir():
        return
    target = Path(target)
    if not target.is_absolute() or target.resolve() != target or board_id not in target.parts:
        raise StorageConfigurationError('Imported content root is redirected or outside its generation')
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Private Board import stage contains a symlink')
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if destination.resolve() != destination:
            raise StorageConfigurationError('Imported content destination is redirected')
        expected = proofs.get(source.name + '/' + relative.as_posix()) or fingerprint(path)
        if destination.exists():
            actual = fingerprint(destination)
        else:
            actual = copy_registered_file(path, destination)
        if actual != expected:
            raise ValueError('Imported content fingerprint mismatch; preserve the stage and target for reconciliation')


def _configuration(row, metadata):
    from utils import atomic_json_write
    home = Path(row['owner_home'])
    directory = home / 'kanban' / 'boards' / row['slug']
    if directory.resolve() != directory:
        raise StorageConfigurationError('Imported Board configuration directory is redirected')
    marker = directory / '.import-id'
    if directory.exists():
        if marker.exists():
            if marker.read_text(encoding='utf-8') != row['board_id']:  # windows-footgun: ok -- Private .import-id is written below with UTF-8; preserve exact generation marker comparison.
                raise StorageConfigurationError('Imported Board configuration belongs to another generation')
        elif any(directory.iterdir()):
            raise StorageConfigurationError('Imported Board configuration directory already contains unrelated files')
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(row['board_id'], encoding='utf-8')
    import time
    clean = {name: str(metadata.get(name) or '') for name in ('name', 'description', 'icon', 'color')}
    clean.update(slug=row['slug'], archived=False, project_id=None, default_workdir=None, created_at=int(time.time()))
    clean['name'] = clean['name'] or row['slug']
    atomic_json_write(directory / 'board.json', clean, indent=2)
    return directory


def _cleanup_stage(row):
    from hermes_cli.kanban_storage_files import _remove_directory
    if not row['stage_root']:
        return False
    try:
        _remove_directory(Path(row['stage_root']), parent=Path(row['owner_home']) / 'kanban' / 'imports')
        return False
    except (OSError, StorageConfigurationError) as error:
        logger.warning('Imported Board %s is active; private stage cleanup is pending: %s', row['slug'], error)
        return True


def finish_import(store, row):
    directory = Path(row['owner_home']) / 'kanban' / 'boards' / row['slug']
    if row['state'] != 'done':
        stage = Path(row['stage_root'])
        expected_parent = Path(row['owner_home']) / 'kanban' / 'imports'
        if not stage.is_relative_to(expected_parent) or stage.resolve() != stage or stage == expected_parent:
            raise StorageConfigurationError('Private Board import stage escaped its owning directory')
        from hermes_cli.kanban_storage_maintenance import owns_import_stage
        if not owns_import_stage(store, stage):
            raise StorageConfigurationError('Private import stage belongs to another database dataset')
        manifest, _tables, metadata = read_archive(stage, private_stage=True)
        for name in ('attachments', 'logs'):
            _publish(stage / name, row[name + '_root'], row['board_id'], manifest['files'])
        directory = _configuration(row, metadata)
        db._activate(store, row)
    pending = _cleanup_stage(row)
    if not pending and row['stage_root'] is not None:
        db.clear_import_stage(store, row)
    return {'new_path': str(directory), 'files_pending': False, 'stage_cleanup_pending': pending}


def _json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError(f'Cannot read Board archive {path.name}') from error


def member_path(root, member):
    if not isinstance(member, str) or '\\' in member or ':' in member or any(part in {'', '.', '..'} for part in member.split('/')) or PurePosixPath(member).is_absolute():
        raise ValueError('Invalid Board archive attachment member')
    path = root.joinpath(*member.split('/'))
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('Board archive member escapes its root')
    return path


def fingerprint(path):
    digest, size = (hashlib.sha256(), 0)
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return {'size': size, 'sha256': digest.hexdigest()}


def _validate_proof(member, proof):
    if not member.startswith('attachments/') or not isinstance(proof, dict) or set(proof) != {'size', 'sha256'} or (type(proof['size']) is not int) or (proof['size'] < 0) or (not isinstance(proof['sha256'], str)) or (re.fullmatch('[0-9a-f]{64}', proof['sha256']) is None):
        raise ValueError('Invalid Board archive attachment fingerprint')


def read_archive(root, *, private_stage=False):
    from hermes_cli.kanban_transfer import ARCHIVE_FORMAT
    manifest = _json(root / 'manifest.json')
    if not isinstance(manifest, dict) or manifest.get('format') != ARCHIVE_FORMAT or type(manifest.get('format_version')) is not int or (manifest['format_version'] != db.FORMAT_VERSION) or (manifest.get('backend') != 'postgresql'):
        raise ValueError('PostgreSQL imports require a PG v2 Board archive; cross-backend migration is unsupported')
    allowed = {'manifest.json', 'board.json', 'data.json', 'attachments', 'logs'}
    if private_stage:
        allowed.add('.owner.json')
    if any(path.name not in allowed for path in root.iterdir()):
        raise ValueError('Unexpected member in PG Board archive')
    data = _json(root / 'data.json')
    if not isinstance(data, dict) or set(data) != {'format_version', 'tables'} or type(data['format_version']) is not int or (data['format_version'] != db.FORMAT_VERSION):
        raise ValueError('Unsupported Board archive data format')
    tables = data['tables']
    db._rows(tables)
    db._graph(tables)
    proofs = manifest.get('files')
    members = {row['stored_path'] for row in tables['task_attachments']}
    if not isinstance(proofs, dict) or set(proofs) != members:
        raise ValueError('Board archive attachment manifest does not match its rows')
    for member, proof in proofs.items():
        _validate_proof(member, proof)
        path = member_path(root, member)
        if not path.is_file() or fingerprint(path) != proof:
            raise ValueError('Board archive attachment fingerprint mismatch')
    metadata = _json(root / 'board.json')
    if not isinstance(metadata, dict):
        raise ValueError('Board archive display metadata must be an object')
    return (manifest, tables, metadata)
