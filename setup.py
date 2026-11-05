"""Build a wheel with an allow-list of immutable runtime assets; never bundle user data."""
from pathlib import Path
import shutil
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py

BASE = Path(__file__).parent
places = ['src', 'contracts/python', 'excel/core', 'excel/payoff', 'excel/statements']
package_dir = {}
for place in places:
    for package in find_packages(place):
        package_dir[package] = str(Path(place) / package.replace('.', '/'))

ASSETS = {
    'contracts': ['VERSION'],
    'contracts/schemas': ['command.schema.json','command_result.schema.json','common.schema.json','import_profile.schema.json',
        'ledger_bundle.schema.json','module_manifest.schema.json','net_worth_report.schema.json','payoff_result.schema.json',
        'payoff_scenario.schema.json','report_tables.json','staging_batch.schema.json'],
    'config/privacy': ['defaults.json','perfin_privacy_checks.py','nopii-export-envelope.schema.json'],
    'access/schema': ['010_tables.sql','020_checks.sql','030_indexes.sql','040_report_views.sql'],
    'access/setup': ['Get-PerfinEnvironment.ps1','PerfinSetup.bas'],
    'excel/core/vba': ['PerFinCommands.bas','PerFinCore.bas','PerFinLauncher.bas','PerFinSelfTest.bas','PerFinSetup.bas'],
    'excel/core/powerquery': ['PerFinDataRoot.pq','PerFinStaleDays.pq','fnPerFinParse.pq','fnPerFinReadCsv.pq','fnPerFinRoot.pq',
        'perfin_modules.pq','perfin_batch_versions.pq','perfin_refresh_status.pq','perfin_statement_recon.pq','perfin_unreconciled_items.pq','queries.txt',
        'rpt_accounts.pq','rpt_card_status.pq','rpt_reconciliation.pq','rpt_review_queue.pq','rpt_statements.pq','rpt_transactions.pq',
        'optional/fnPerFinReadAccess.pq'],
}


class Build(build_py):
    def run(self):
        super().run()
        dest = Path(self.build_lib) / 'perfin_resources' / 'data'
        if dest.exists():
            shutil.rmtree(dest)
        for folder, names in ASSETS.items():
            for name in names:
                target = dest / folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(BASE / folder / name, target)

setup(packages=list(package_dir), package_dir=package_dir,
      package_data={'perfin_import': ['builtin_profiles/*.json'], 'perfin_pdf': ['module_manifest.json'],
                    'perfin_excel_payoff': ['module_manifest.json'], 'perfin_excel_statements': ['module_manifest.json']},
      cmdclass={'build_py': Build})
