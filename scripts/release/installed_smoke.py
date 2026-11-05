"""Installed-wheel smoke. Run with the wheel's Python, outside the checkout.

    path/to/venv/python -I path/to/source/scripts/release/installed_smoke.py

No network or Office dependency is substituted. This verifies packaged modules,
real SQLite persistence/backup/restore and generated OOXML; native checks remain.
"""
from __future__ import annotations

from datetime import datetime
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[2]
MODULES = ('perfin_contracts', 'perfin_import', 'perfin_store', 'perfin_app', 'perfin_resources',
           'perfin_excel_core', 'perfin_payoff', 'perfin_excel_payoff', 'perfin_statements',
           'perfin_excel_statements', 'perfin_pdf')


def main():
    for name in MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if path == SOURCE or SOURCE in path.parents:
            raise RuntimeError('source checkout leaked into installed smoke: ' + name)
    from perfin_resources import root
    from perfin_contracts import CONTRACT_VERSION
    from perfin_contracts.semantic import validate_document
    from perfin_import import builtin_profiles
    from perfin_excel_core.workbook import build as core_build
    from perfin_payoff import simulate
    from perfin_excel_payoff import build as payoff_build, read_scenario
    from perfin_statements import build_statements
    from perfin_excel_statements import build as statements_build
    from perfin_app.__main__ import demo_bundle
    from perfin_app.paths import initialize_layout
    from perfin_app.service import FinanceApp, accepted
    from perfin_store.sqlite_backend import create_database, open_database
    from perfin_store import sqlite_backup
    if SOURCE in root().resolve().parents or root().resolve() == SOURCE:
        raise RuntimeError('schemas resolved through source checkout')
    profiles = builtin_profiles()
    if len(profiles) < 3:
        raise RuntimeError('installed builtin profiles missing')
    bundle = demo_bundle(CONTRACT_VERSION)
    if validate_document(bundle):
        raise RuntimeError('installed schema validation failed')
    details = build_statements(bundle, as_of='2026-02-28', period_start='2026-02-01')
    scenario = {'contract': 'perfin', 'contract_version': CONTRACT_VERSION, 'document_type': 'payoff_scenario',
                'scenario': {'scenario_id': 'installed-smoke', 'as_of': '2026-01-31', 'horizon_months': 3,
                'accrual_model': 'm1_monthly_apr_div_12', 'cash_plan': {'monthly_minor': 10000},
                'cards': [{'account_id': 'card:synthetic', 'source_statement_id': None, 'buckets': [{'bucket_id': 'purchase',
                    'balance_minor': 10000, 'apr': '0', 'deferred_interest': False}],
                    'min_payment_rule': {'rule_type': 'fixed', 'amount_minor': 1000}}],
                'strategies': [{'kind': 'avalanche'}, {'kind': 'largest_balance'}],
                'tolerance': {'max_extra_cost_minor': None, 'max_payoff_delay_months': None}}}
    result = simulate(scenario)
    if validate_document(result):
        raise RuntimeError('installed payoff result invalid')
    with tempfile.TemporaryDirectory(prefix='perfin-installed-smoke-') as d:
        data = Path(d)
        (data / 'perfin-data-dir.json').write_text(json.dumps({'kind': 'synthetic', 'created': '2026-11-05'}))
        core_build(data / 'core.xlsx')
        payoff_build(scenario, data / 'payoff.xlsx', data_root=data)
        if read_scenario(data / 'payoff.xlsx')['scenario']['cards'] != scenario['scenario']['cards']:
            raise RuntimeError('installed payoff workbook roundtrip failed')
        statements_build(details, data / 'statements.xlsx', data_root=data)
        root_dir = initialize_layout(data / 'finance', synthetic=True)
        database = root_dir / 'db/perfin.sqlite'
        create_database(database)
        repo = open_database(database)
        try:
            accepted(repo.import_bundle(bundle))
            accepted(repo.set_default_categories('expenses', 'income'))
            app = FinanceApp(repo, root_dir)
            profile = profiles[('synthetic_checking_signed', '1.0.0')]
            staged = app.import_csv(b'Date,Description,Amount,Balance,Transaction ID\n02/01/2026,SYNTHETIC SHOP,-25.00,,smoke-1\n',
                                    'synthetic.csv', profile, 'chk:main')
            batch_id = staged['document']['batch']['batch_id']
            app.review(batch_id, approve=[1])
            app.commit(batch_id)
            if repo.summary()['account_balances_minor']['chk:main'] != 247500:
                raise RuntimeError('installed SQLite command path returned wrong balance')
            expected = repo.summary()
        finally:
            repo.adapter.close()
        saved = sqlite_backup.create_backup(database, root_dir / 'backups', summary=expected)
        restored = root_dir / 'db/restored.sqlite'
        sqlite_backup.restore_backup(saved, restored)
        repo = open_database(restored)
        try:
            if repo.summary() != expected:
                raise RuntimeError('installed SQLite restore lost balances/history')
        finally:
            repo.adapter.close()
        for name in ('perfin_app', 'perfin_payoff', 'perfin_excel_payoff', 'perfin_excel_statements', 'perfin_pdf'):
            subprocess.run([sys.executable, '-I', '-B', '-m', name, '--help'], cwd=data, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for name in ('perfin_pdf', 'perfin_excel_payoff', 'perfin_excel_statements'):
        package = importlib.import_module(name)
        manifest = Path(package.__file__).parent / 'module_manifest.json'
        if not manifest.is_file() or validate_document(json.loads(manifest.read_text())):
            raise RuntimeError('installed module manifest missing/invalid: ' + name)
    print('PASS installed wheel resources, real SQLite reviewed import/backup/restore, engines, workbooks and CLI help')
    print('PENDING Windows/ACE, desktop Excel, Power Query and VBA runtime acceptance')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
