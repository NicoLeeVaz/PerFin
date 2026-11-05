"""Opt-in registration of a reviewed, standalone XLSX; never downloads or opens it.

Run from a source checkout with PerFin installed. No database is opened.
Operator evidence is an attestation, not independent runtime verification.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from perfin_app.paths import checked_root, child
from perfin_excel_core.offline_check import check_workbook
from perfin_excel_core.registry import scan
from perfin_contracts.semantic import validate_document

MAX_BYTES = 20 * 1024 * 1024


def inspect_bytes(data):
    if len(data) > MAX_BYTES:
        raise ValueError('Workbook exceeds 20 MiB')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = z.infolist()
        if len(entries) > 5000 or sum(x.file_size for x in entries) > 100 * 1024 * 1024:
            raise ValueError('Expanded workbook exceeds inspection limits')
        names = [x.filename.lower() for x in entries]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate package members')
        forbidden = ('vba', 'macrosheet', 'activex', 'embeddings/', 'externallinks/',
                     'connections.xml', 'querytables/', 'webextension', 'customxml/')
        if any(any(token in name for token in forbidden) for name in names):
            raise ValueError('Only standalone macro-free, connection-free XLSX is supported')
        if 'xl/workbook.xml' not in names:
            raise ValueError('Not an XLSX workbook')
    with tempfile.TemporaryDirectory(prefix='perfin-extra-check-') as temp:
        path = Path(temp) / 'Workbook.xlsx'
        path.write_bytes(data)
        findings = check_workbook(path)
    return {'sha256': hashlib.sha256(data).hexdigest(),
            'findings': [dict(f._asdict()) for f in findings],
            'static_clean': not any(f.severity in ('ERROR', 'WARN') for f in findings),
            'native_excel_verified_by_tool': False}


def read_workbook(path):
    path = Path(path)
    if path.suffix.lower() != '.xlsx' or path.is_symlink():
        raise ValueError('Choose a regular .xlsx file, not a macro workbook or symlink')
    with path.open('rb') as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Workbook exceeds 20 MiB')
    return data


def register(workbook, data_root, module_id, evidence):
    if not re.fullmatch(r'extra_[a-z0-9_]{1,48}', module_id):
        raise ValueError('Module ID must start extra_ followed by lowercase letters, digits or underscores')
    data = read_workbook(workbook)
    report = inspect_bytes(data)
    if not report['static_clean']:
        raise ValueError('Static findings need review; no automatic bypass')
    if not isinstance(evidence, dict) or evidence.get('sha256') != report['sha256']:
        raise ValueError('Evidence must match the exact workbook SHA256')
    for field in ('license_reviewed', 'synthetic_math_checked', 'desktop_offline_checked'):
        if evidence.get(field) is not True:
            raise ValueError('Missing operator evidence: ' + field)
    for field in ('source_url', 'license', 'tested_environment', 'reviewed_by', 'notes'):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise ValueError('Missing evidence text: ' + field)
    if not evidence['source_url'].startswith('https://'):
        raise ValueError('Record the HTTPS publisher source URL')
    root = checked_root(data_root)
    folder = child(root, 'workbooks/' + module_id)
    if folder.exists() or folder.is_symlink():
        raise ValueError('Module already exists; use a new reviewed version ID')
    if any(entry['module_id'] == module_id for entry in scan(folder.parent)):
        raise ValueError('Module ID is already registered in another folder')
    manifest = {'contract': 'perfin', 'contract_version': '1.0.1',
                'document_type': 'module_manifest', 'module_id': module_id,
                'module_version': '1.0.0', 'module_kind': 'excel_workbook',
                'contract_versions': {'min': '1.0.1', 'max_exclusive': '1.1.0'},
                'workbook_file': 'Workbook.xlsx', 'reads': [], 'emits': [],
                'commands': [], 'writes_ledger': False}
    if validate_document(manifest):
        raise ValueError('Invalid module manifest')
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir()  # never overwrite another module, even after a racing install
    try:
        (folder / 'Workbook.xlsx').write_bytes(data)
        (folder / 'review.json').write_text(json.dumps({
            'operator_reported': evidence, 'static_inspection': report,
            'scope': 'standalone what-if; no ledger connection; evidence covers installed bytes only'
        }, indent=2), encoding='utf-8')
        # Manifest is last: incomplete folders are not activated in the registry.
        (folder / 'module_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    except BaseException:
        shutil.rmtree(folder)
        raise
    return str(folder)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('inspect').add_argument('workbook')
    r = sub.add_parser('register')
    r.add_argument('workbook'); r.add_argument('--data-root', required=True)
    r.add_argument('--id', required=True); r.add_argument('--evidence', required=True)
    a = p.parse_args()
    try:
        if a.action == 'inspect':
            result = inspect_bytes(read_workbook(a.workbook))
            print(json.dumps(result, indent=2))
            return 0 if result['static_clean'] else 2
        result = register(a.workbook, a.data_root, a.id,
                          json.loads(Path(a.evidence).read_text(encoding='utf-8')))
        print(json.dumps({'installed': result, 'runtime_evidence': 'operator-reported'}))
        return 0
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        p.exit(2, 'Extra refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
