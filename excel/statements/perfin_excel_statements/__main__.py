import argparse
import json
import tempfile
from pathlib import Path
from perfin_statements import build_statements
from perfin_excel_core.commands import check_data_root, _checked_path
from . import build, queue_valuations


def main(argv=None):
    p=argparse.ArgumentParser(description='Local PerFin statements workbook and valuation commands')
    sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('build');b.add_argument('--bundle',required=True);b.add_argument('--data-root',required=True)
    b.add_argument('--as-of',required=True);b.add_argument('--period-start',required=True)
    b.add_argument('--options',help='JSON with liability_view, stale_days and explicit inclusion_groups')
    q=sub.add_parser('queue-valuations');q.add_argument('--workbook',required=True);q.add_argument('--data-root',required=True)
    args=p.parse_args(argv)
    check_data_root(args.data_root)
    if args.action=='queue-valuations':
        paths=queue_valuations(args.workbook,data_root=args.data_root);print('%d valuation command(s) queued' % len(paths));return 0
    bundle=json.loads(Path(args.bundle).read_text(encoding='utf-8'))
    options=json.loads(Path(args.options).read_text(encoding='utf-8')) if args.options else {}
    details=build_statements(bundle,as_of=args.as_of,period_start=args.period_start,**options)
    folder=_checked_path(Path(args.data_root)/'workbooks/excel_statements',args.data_root)
    out=build(details,folder/'PerFin-Statements.xlsx',data_root=args.data_root)
    manifest=json.loads((Path(__file__).parent/'module_manifest.json').read_text(encoding='utf-8'))
    target = _checked_path(folder/'module_manifest.json', args.data_root)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                         prefix='.manifest-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(manifest,indent=2)+'\n')
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
    print('Statements workbook refreshed; %d review warning(s)' % len(details['net_worth']['warnings']))
    return 0


if __name__=='__main__':raise SystemExit(main())
