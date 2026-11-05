"""Apply the local privacy boundary before every application-owned write."""
import json
import os
from pathlib import Path
from perfin_store import _paths


class LocationError(ValueError):
    pass


def default_root():
    if os.environ.get('PERFIN_DATA_DIR'):
        return Path(os.environ['PERFIN_DATA_DIR'])
    if os.name == 'nt':
        if not os.environ.get('LOCALAPPDATA'):
            raise LocationError('LOCALAPPDATA is unavailable; choose --data-root explicitly')
        return Path(os.environ['LOCALAPPDATA']) / 'PerFin'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'perfin'


def checked_root(path=None, acknowledge=False):
    root = Path(path or default_root()).expanduser().absolute()
    decision = _paths.privacy().evaluate_data_dir(root)
    if decision['decision'] == 'refuse' or (decision['decision'] == 'warn' and not acknowledge):
        raise LocationError('; '.join(decision['reasons']))
    return root.resolve()


def child(root, relative, acknowledge=False):
    root = checked_root(root, acknowledge)
    target = root / relative
    try:
        target.resolve().relative_to(root)
    except ValueError:
        raise LocationError('destination escapes the data root') from None
    checked_root(target, acknowledge)
    return target


def initialize_layout(root, acknowledge=False, synthetic=False):
    root = checked_root(root, acknowledge)
    marker = child(root, 'perfin-data-dir.json', acknowledge)
    dirs = _paths.privacy().load_defaults()['data_dir']['subdirs']
    dirs += ['reports', 'commands/drafts', 'commands/outbox', 'commands/processed', 'commands/rejected']
    # Validate the entire layout before creating anything.
    paths = [child(root, d, acknowledge) for d in dirs]
    root.mkdir(parents=True, exist_ok=True)
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({'kind': 'synthetic' if synthetic else 'real', 'app': 'PerFin'}), encoding='utf-8')
    return root
