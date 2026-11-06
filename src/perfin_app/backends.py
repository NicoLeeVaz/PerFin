"""Choose one authoritative database per data root, without silent fallback."""
import json
from dataclasses import dataclass
from pathlib import Path

from .paths import child
from .service import WorkflowError


DATABASES = {'sqlite': 'db/perfin.sqlite', 'access': 'db/perfin.accdb'}


@dataclass(frozen=True)
class Selection:
    backend: str
    path: Path


def select_backend(root, requested=None, *, acknowledge=False, default='sqlite'):
    """New roots default to SQLite; existing roots must retain their backend."""
    marker = child(root, 'perfin-data-dir.json', acknowledge)
    metadata = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
    if not isinstance(metadata, dict) or metadata.get('app', 'PerFin') != 'PerFin':
        raise WorkflowError('Invalid PerFin data-root metadata')
    stored = metadata.get('backend')
    if stored is not None and stored not in DATABASES:
        raise WorkflowError('Unsupported backend in data-root metadata')
    if 'database' in metadata and (stored is None or metadata['database'] != DATABASES[stored]):
        raise WorkflowError('Data-root database does not match its selected backend')
    paths = {name: child(root, relative, acknowledge) for name, relative in DATABASES.items()}
    existing = [name for name, path in paths.items() if path.exists()]
    if len(existing) > 1:
        raise WorkflowError('Both SQLite and Access databases exist in this root; use separate data roots')
    detected = existing[0] if existing else None
    if stored and detected and stored != detected:
        raise WorkflowError('Stored backend differs from the database present; repair the data-root selection explicitly')
    chosen = stored or detected or requested or default
    if requested and chosen != requested:
        raise WorkflowError('This root already uses %s; choose a separate root for %s' % (chosen, requested))
    return Selection(chosen, paths[chosen])


def record_backend(root, selection, *, acknowledge=False):
    """Persist selection only after successful initialization of a new database."""
    marker = child(root, 'perfin-data-dir.json', acknowledge)
    metadata = json.loads(marker.read_text(encoding='utf-8'))
    metadata.update(backend=selection.backend, database=DATABASES[selection.backend])
    marker.write_text(json.dumps(metadata, indent=2), encoding='utf-8')


def operations(backend):
    if backend == 'sqlite':
        from perfin_store.sqlite_backend import create_database, open_database
        from perfin_store import sqlite_backup
        return open_database, create_database, sqlite_backup
    from perfin_store.__main__ import open_access
    from perfin_store import setup, backup
    return open_access, setup.create_database, backup
