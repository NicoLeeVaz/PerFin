"""Application orchestration with explicit human decisions and no network clients."""
import json
import uuid
from datetime import date, datetime
from pathlib import Path
from perfin_import import stage_file
from perfin_store import reports
from perfin_store.__main__ import make_command, batch_version
from perfin_store.repository import utc_now
from .paths import checked_root, child


class WorkflowError(ValueError):
    pass


def same_request(left, right):
    # Retry timestamps may change; payload, actor, contract and versions may not.
    return ({k: v for k, v in left.items() if k != 'issued_at'} ==
            {k: v for k, v in right.items() if k != 'issued_at'})


def accepted(result):
    if result['result_status'] not in ('accepted', 'replayed'):
        raise WorkflowError('; '.join(e['code'] + ': ' + (e.get('message') or '') for e in result['errors']))
    return result


class ImportView:
    """Read-only adapter for the imported ledger and original staging fingerprints."""
    def __init__(self, repo):
        self.repo = repo

    def get_account(self, account_id):
        return self.repo._one('account', {'account_id': account_id})

    def prior_batches(self, account_id):
        return self.repo._rows('import_batch', {'account_id': account_id})

    def transactions(self):
        transactions = self.repo._rows('ledger_txn')
        for t in transactions:
            # Keep original rows as conservative duplicate evidence even after
            # reversals (including reversal-of-reversal); never silently hide them.
            if t['entry_method'] == 'reversal':
                continue
            row = dict(t)
            if t['source_batch_id']:
                sr = self.repo._one('staging_row', {'batch_id': t['source_batch_id'], 'row_number': t['source_row_number']})
                row['fingerprint'] = sr['fingerprint'] if sr else None
            yield row

    def find_candidates(self, account_id, posted_date, amount_minor, window_days):
        return [t for t in self.transactions() if t['account_id'] == account_id and t['amount_minor'] == amount_minor
                and abs((date.fromisoformat(t['posted_date']) - date.fromisoformat(posted_date)).days) <= window_days]

    def find_by_source_txn_id(self, account_id, source_txn_id):
        return [t for t in self.transactions() if t['account_id'] == account_id and t['source_txn_id'] == source_txn_id]

    def find_transfer_candidates(self, exclude_account_id, amount_minor, posted_date, window_days):
        linked = {s['transaction_id'] for s in self.repo._rows('split') if s['split_kind'] == 'transfer'}
        linked.update(t['reverses_transaction_id'] for t in self.repo._rows('ledger_txn') if t['reverses_transaction_id'])
        return [t for t in self.transactions() if t['account_id'] != exclude_account_id and t['amount_minor'] == amount_minor
                and t['transaction_id'] not in linked
                and abs((date.fromisoformat(t['posted_date']) - date.fromisoformat(posted_date)).days) <= window_days]


class FinanceApp:
    def __init__(self, repo, data_root, acknowledge=False):
        self.repo = repo
        self.root = checked_root(data_root, acknowledge)
        self.acknowledge = acknowledge

    def path(self, relative):
        return child(self.root, relative, self.acknowledge)

    def import_csv(self, data, filename, profile, account_id):
        result = stage_file(data, filename, profile, account_id, ImportView(self.repo),
                            batch_id='imp-' + uuid.uuid4().hex[:24])
        # An already reviewed batch is the source of truth; display it unchanged.
        existing = self.repo._one('import_batch', {'account_id': account_id,
                                  'source_file_sha256': result.document['batch']['source_file_sha256']})
        if existing:
            if existing['batch_status'] == 'rolled_back':
                raise WorkflowError('This file was rolled back. Preserve its audit history; use an explicit correction entry, not re-import.')
            return {'result_status': 'replayed', 'document': self.repo.export_staging_batch(existing['batch_id']),
                    'batch_row_version': existing['row_version']}
        accepted(self.repo.stage_batch(result.document))
        return self.preview(result.document['batch']['batch_id'])

    def import_pdf(self, data, filename, account_id, layout_id='perfin.synthetic.statement.v1'):
        from perfin_pdf import stage_pdf
        result = stage_pdf(data, filename, account_id, ImportView(self.repo), layout_id=layout_id)
        saved = accepted(self.repo.stage_batch(result.document))
        batch_id = result.document['batch']['batch_id']
        if saved['result_status'] == 'replayed':
            batch_id = self.repo._one('import_batch', {'account_id': account_id, 'source_file_sha256': result.document['batch']['source_file_sha256']})['batch_id']
        # The stage payload remains audited in the ledger; this local sidecar is extraction evidence.
        p = self.path('staging/' + batch_id + '.pdf-provenance.json')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result.provenance, indent=2), encoding='utf-8')
        return self.preview(batch_id)

    def preview(self, batch_id):
        document = self.repo.export_staging_batch(batch_id)
        if document is None:
            raise WorkflowError('Unknown batch')
        return {'result_status': 'preview', 'document': document,
                'batch_row_version': batch_version(self.repo, batch_id)[0]['row_version']}

    def command(self, document):
        return accepted(self.repo.execute(document))

    def run(self, command_type, payload, expected=()):
        return self.command(make_command(self.repo, command_type, payload, list(expected), issued_by='cli:perfin'))

    def review(self, batch_id, *, approve=(), reject=(), reason=None, resolve=()):
        for row_number, resolution in resolve:
            self.run('resolve_duplicate', {'batch_id': batch_id, 'row_number': row_number, 'resolution': resolution},
                     batch_version(self.repo, batch_id))
        if approve:
            self.run('approve_rows', {'batch_id': batch_id, 'row_numbers': list(approve)}, batch_version(self.repo, batch_id))
        if reject:
            self.run('reject_rows', {'batch_id': batch_id, 'row_numbers': list(reject), 'reason': reason},
                     batch_version(self.repo, batch_id))
        return self.preview(batch_id)

    def commit(self, batch_id):
        preview = self.preview(batch_id)
        b = preview['document']['batch']
        return self.run('commit_batch', {'batch_id': batch_id, 'source_file_sha256': b['source_file_sha256']},
                        batch_version(self.repo, batch_id))

    def link_transfer(self, from_id, to_id):
        expected = []
        for tid in (from_id, to_id):
            t = self.repo.transaction(tid)
            if t is None:
                raise WorkflowError('Unknown transfer transaction')
            expected.append({'entity': 'transaction', 'entity_id': tid, 'row_version': t['row_version']})
        return self.run('link_transfer', {'transfer_link_id': 'link-' + uuid.uuid4().hex[:24],
                        'from_transaction_id': from_id, 'to_transaction_id': to_id,
                        'link_status': 'confirmed', 'match_evidence': 'explicit user confirmation'}, expected)

    def snapshot(self):
        return self.repo.export_bundle()

    def refresh(self, as_of=None):
        from perfin_excel_core import workbook, registry, reports as excel_reports, spec
        report_dir = self.path('reports')
        report_dir.mkdir(parents=True, exist_ok=True)
        for t in reports.STORE_TABLES:
            self.path('reports/' + t + '.csv')
        reports.export_csv(self.repo, report_dir, as_of, acknowledge_location=self.acknowledge)
        excel_reports.write_report_csv(self.path('reports/perfin_batch_versions.csv'), spec.BATCH_VERSIONS_TABLE,
            [{'batch_id': b['batch_id'], 'row_version': b['row_version']} for b in self.repo._rows('import_batch')])
        registry.export_csv(self.path('workbooks'), self.path('reports/perfin_modules.csv'))
        out = self.path('workbooks/PerFin-Core.xlsx')
        workbook.build(out, report_dir=report_dir, modules_dir=self.path('workbooks'), checked_at=datetime.now())
        # Explicit local refresh generates the read-only core view. No Excel COM on Linux.
        from openpyxl import load_workbook
        wb = load_workbook(out)
        wb['Settings']['B4'] = str(self.root)
        wb.save(out)
        return {'workbook': str(out), 'as_of': as_of or date.today().isoformat(),
                'desktop_excel_verified': False}

    def payoff(self, document, replace=False):
        import perfin_excel_payoff
        from perfin_excel_payoff import build, save_command
        from perfin_payoff import simulate
        result = simulate(document)
        folder = self.path('workbooks/excel_payoff')
        folder.mkdir(parents=True, exist_ok=True)
        output = self.path('workbooks/excel_payoff/PerFin-Payoff.xlsx')
        build(document, output, data_root=self.root, overwrite=replace)
        manifest = Path(perfin_excel_payoff.__file__).parent / 'module_manifest.json'
        self.path('workbooks/excel_payoff/module_manifest.json').write_text(manifest.read_text(encoding='utf-8'), encoding='utf-8')
        self.command(save_command(document))
        return {'workbook': str(output), 'result': result}

    def statements(self, as_of, period_start, options=None):
        import perfin_excel_statements
        from perfin_excel_statements import build
        from perfin_statements import build_statements
        details = build_statements(self.snapshot(), as_of=as_of, period_start=period_start, **(options or {}))
        folder = self.path('workbooks/excel_statements')
        folder.mkdir(parents=True, exist_ok=True)
        output = self.path('workbooks/excel_statements/PerFin-Statements.xlsx')
        build(details, output, data_root=self.root, acknowledged=self.acknowledge)
        manifest = Path(perfin_excel_statements.__file__).parent / 'module_manifest.json'
        self.path('workbooks/excel_statements/module_manifest.json').write_text(manifest.read_text(encoding='utf-8'), encoding='utf-8')
        return {'workbook': str(output), 'complete': details['complete'], 'warnings': details['net_worth']['warnings']}

    def process_outbox(self):
        from perfin_excel_core.commands import promote_drafts
        promotion = promote_drafts(self.root, self.acknowledge)
        results = []
        for p in sorted(self.path('commands/outbox').glob('*.json')):
            self.path(p.relative_to(self.root))
            doc = json.loads(p.read_text(encoding='utf-8'))
            # A repeated command ID is only idempotent for the identical request.
            prior = self.repo._one('command_log', {'command_id': doc.get('command_id')}) if isinstance(doc, dict) else None
            if prior and not same_request(json.loads(prior['payload_json']), doc):
                raise WorkflowError('Command ID was already used for a different request')
            # Never silently replace optimistic versions with current ones: stale commands need review.
            result = self.repo.execute(doc)
            folder = 'processed' if result['result_status'] in ('accepted', 'replayed') else 'rejected'
            dest = self.path('commands/' + folder + '/' + p.name)
            receipt = self.path('commands/' + folder + '/' + p.stem + '.result.json')
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or receipt.exists():
                if (result['result_status'] == 'replayed' and dest.is_file() and receipt.is_file()
                        and same_request(json.loads(dest.read_text(encoding='utf-8')), doc)
                        and json.loads(receipt.read_text(encoding='utf-8'))['result_status'] in ('accepted', 'replayed')):
                    p.unlink()
                    results.append(result)
                    continue
                raise WorkflowError('Command receipt already exists; inspect the command ID before retrying')
            receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
            p.replace(dest)
            results.append(result)
        return {'promotion': promotion, 'results': results}
