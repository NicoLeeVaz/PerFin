"""Find immutable source assets in a checkout or in an installed wheel."""
from pathlib import Path


def root():
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / 'contracts' / 'schemas').is_dir():
        return checkout
    installed = Path(__file__).resolve().parent / 'data'
    if not (installed / 'contracts' / 'schemas').is_dir():
        raise RuntimeError('PerFin resources are missing; reinstall the complete package')
    return installed
