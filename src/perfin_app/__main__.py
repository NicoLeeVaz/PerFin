"""PerFin local launcher; all money arguments are signed integer cents."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from perfin_store.repository import utc_now, derive_id
from perfin_import import builtin_profiles, load_profile
from .paths import checked_root, child, initialize_layout
from .service import FinanceApp, WorkflowError, accepted
from .backends import select_backend, record_backend, operations


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def demo_bundle(version='1.0.1'):
    accounts = []
    for aid, kind, cls, value in [('chk:main','asset','checking',250000),('card:a','liability','credit_card',-20000),
                                   ('card:b','liability','credit_card',-10000)]:
        accounts.append({'account_id': aid, 'kind': kind, 'account_class': cls, 'display_name': 'SYNTHETIC '+aid,
                         'currency': 'USD', 'opening_balance_minor': value, 'opening_balance_date': '2026-01-01',
                         'row_version': 1, 'include_in_net_worth': True})
    return {'contract':'perfin','contract_version':version,'document_type':'ledger_bundle','base_currency':'USD',
            'accounts':accounts,'categories':[{'category_id':'expenses','name':'Uncategorized expenses','category_kind':'expense'},
            {'category_id':'income','name':'Uncategorized income','category_kind':'income'}],'transactions':[]}


def parser():
    p=argparse.ArgumentParser(prog='perfin',description=__doc__)
    p.add_argument('--data-root');p.add_argument('--acknowledge-location',action='store_true')
    p.add_argument('--backend', choices=['sqlite', 'access'],
                   help='SQLite for new roots by default; existing roots retain their selected backend')
    sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('init');s.add_argument('--demo',action='store_true');s.add_argument('--engine',choices=['odbc','adox'],default='odbc')
    sub.add_parser('gui');sub.add_parser('envcheck')
    for name in ['onboard','command']:
        sub.add_parser(name).add_argument('file')
    a=sub.add_parser('account-add');a.add_argument('id');a.add_argument('--name',required=True)
    a.add_argument('--class',dest='account_class',required=True);a.add_argument('--kind',choices=['asset','liability'],required=True)
    a.add_argument('--opening-cents',type=int,required=True);a.add_argument('--opening-date',required=True);a.add_argument('--currency',default='USD')
    s=sub.add_parser('import');s.add_argument('file');s.add_argument('--account',required=True);s.add_argument('--profile',required=True)
    s=sub.add_parser('import-pdf');s.add_argument('file');s.add_argument('--account',required=True);s.add_argument('--layout',default='perfin.synthetic.statement.v1')
    for name in ['preview','commit']:
        sub.add_parser(name).add_argument('batch')
    s=sub.add_parser('review');s.add_argument('batch');s.add_argument('--approve');s.add_argument('--reject');s.add_argument('--reason');s.add_argument('--resolve',action='append',default=[])
    s=sub.add_parser('link-transfer');s.add_argument('from_id');s.add_argument('to_id')
    s=sub.add_parser('statement-add');s.add_argument('id');s.add_argument('--account',required=True)
    s.add_argument('--start',required=True);s.add_argument('--end',required=True)
    s.add_argument('--opening-cents',type=int,required=True);s.add_argument('--closing-cents',type=int,required=True)
    s.add_argument('--due-date');s.add_argument('--minimum-cents',type=int)
    s=sub.add_parser('profile-create');s.add_argument('id');s.add_argument('--account-class',required=True)
    s.add_argument('--date-column',required=True);s.add_argument('--description-column',required=True);s.add_argument('--amount-column',required=True)
    s.add_argument('--date-format',required=True);s.add_argument('--sign',choices=['as_is','invert'],required=True)
    s.add_argument('--decimal',choices=['.',','],default='.');s.add_argument('--delimiter',default=',');s.add_argument('--encoding',default='utf-8')
    s=sub.add_parser('reconcile');s.add_argument('statement');s.add_argument('--transactions',required=True)
    s=sub.add_parser('refresh');s.add_argument('--as-of')
    s=sub.add_parser('payoff');s.add_argument('scenario');s.add_argument('--replace',action='store_true')
    s=sub.add_parser('payoff-current');s.add_argument('--as-of',required=True);s.add_argument('--monthly-cents',type=int,required=True);s.add_argument('--replace',action='store_true')
    s=sub.add_parser('statements');s.add_argument('--as-of',required=True);s.add_argument('--period-start',required=True);s.add_argument('--options')
    s=sub.add_parser('snapshot');s.add_argument('--out',default='exports/ledger.json')
    sub.add_parser('process-outbox');sub.add_parser('backup');sub.add_parser('status')
    s=sub.add_parser('restore');s.add_argument('backup_set');s.add_argument('--target',required=True)
    return p


def main(argv=None, *, open_repo=None, create_db=None):
    args=parser().parse_args(argv)
    repo=None
    try:
        root=checked_root(args.data_root,args.acknowledge_location)
        selection=select_backend(root,args.backend,acknowledge=args.acknowledge_location,
                                 default='access' if open_repo is not None or create_db is not None else 'sqlite')
        if args.action=='envcheck':
            if selection.backend=='access':
                from perfin_store.envcheck import main as check
                return check([])
            ready=sqlite3.sqlite_version_info >= (3,37,0)
            print(json.dumps({'backend':'sqlite','sqlite_version':sqlite3.sqlite_version,'platform':sys.platform,
                              'ready':ready,'requires':'SQLite >= 3.37',
                              'native_access_excel':'not checked'},indent=2));return 0 if ready else 2
        if args.action=='gui':
            from .gui import launch
            launch(root,args.acknowledge_location,selection.backend);return 0
        default_open,default_create,backup=operations(selection.backend)
        open_repo=open_repo or default_open
        create_db=create_db or default_create
        db=selection.path
        if args.action=='init':
            initialize_layout(root,args.acknowledge_location,args.demo)
            create_options={'acknowledge_location':args.acknowledge_location}
            if selection.backend=='access':create_options['engine']=args.engine
            create_db(db,**create_options)
        if args.action=='restore':
            target=child(root,args.target,args.acknowledge_location)
            extensions=('.sqlite3','.sqlite','.db') if selection.backend=='sqlite' else ('.accdb',)
            if target.suffix.lower() not in extensions:
                raise WorkflowError('Restore target extension does not match the %s backend' % selection.backend)
            def summary(path):
                r=open_repo(str(path))
                try:return r.summary()
                finally:r.adapter.close()
            result=backup.restore_backup(args.backup_set,target,open_summary=summary,acknowledge_location=args.acknowledge_location)
            print(json.dumps(result,indent=2));return 0
        repo=open_repo(str(db));app=FinanceApp(repo,root,args.acknowledge_location)
        if args.action=='init':
            if args.demo: accepted(repo.import_bundle(demo_bundle(repo.contract_version)))
            else:
                minimal=demo_bundle(repo.contract_version);minimal['accounts']=[]
                accepted(repo.import_bundle(minimal))
            result=accepted(repo.set_default_categories('expenses','income'))
            record_backend(root,selection,acknowledge=args.acknowledge_location)
        elif args.action=='onboard':result=accepted(repo.import_bundle(read_json(args.file)))
        elif args.action=='account-add':
            bundle={'contract':'perfin','contract_version':repo.contract_version,'document_type':'ledger_bundle',
                    'base_currency':repo.base_currency,'accounts':[{'account_id':args.id,'kind':args.kind,'account_class':args.account_class,
                    'display_name':args.name,'currency':args.currency,'opening_balance_minor':args.opening_cents,
                    'opening_balance_date':args.opening_date,'row_version':1,'include_in_net_worth':True}], 'categories':[],'transactions':[]}
            result=accepted(repo.import_bundle(bundle))
        elif args.action=='import':
            profiles=builtin_profiles();profile=next((p for p in profiles.values() if p['profile_id']==args.profile),None)
            profile=profile or load_profile(args.profile)
            result=app.import_csv(Path(args.file).read_bytes(),Path(args.file).name,profile,args.account)
        elif args.action=='import-pdf': result=app.import_pdf(Path(args.file).read_bytes(),Path(args.file).name,args.account,args.layout)
        elif args.action=='preview':result=app.preview(args.batch)
        elif args.action=='review':
            nums=lambda s:[int(n) for n in s.split(',')] if s else []
            result=app.review(args.batch,approve=nums(args.approve),reject=nums(args.reject),reason=args.reason,
                             resolve=[(int(x.split('=')[0]),x.split('=')[1]) for x in args.resolve])
        elif args.action=='commit':result=app.commit(args.batch)
        elif args.action=='command':result=app.command(read_json(args.file))
        elif args.action=='link-transfer':result=app.link_transfer(args.from_id,args.to_id)
        elif args.action=='statement-add':
            payload={'statement_id':args.id,'account_id':args.account,'period_start':args.start,'period_end':args.end,
                     'opening_balance_minor':args.opening_cents,'closing_balance_minor':args.closing_cents}
            if args.due_date:payload['due_date']=args.due_date
            if args.minimum_cents is not None:payload['minimum_due_minor']=args.minimum_cents
            prior=repo._one('statement',{'statement_id':args.id})
            expected=[{'entity':'statement','entity_id':args.id,'row_version':prior['row_version']}] if prior else []
            result=app.run('record_statement',payload,expected)
        elif args.action=='profile-create':
            from perfin_import.profiles import profile_from_mapping
            profile=profile_from_mapping({args.date_column:'posted_date',args.description_column:'description',args.amount_column:'amount'},
                    profile_id=args.id,profile_version='1.0.0',account_class=args.account_class,date_format=args.date_format,
                    sign_rule=args.sign,decimal_separator=args.decimal,delimiter=args.delimiter,encoding=args.encoding)
            out=app.path('config/'+args.id+'.json')
            if out.exists():raise WorkflowError('Profile already exists; edit/version it explicitly')
            out.write_text(json.dumps(profile,indent=2),encoding='utf-8');result={'profile':str(out)}
        elif args.action=='reconcile':
            st=repo._one('statement',{'statement_id':args.statement})
            if st is None:raise WorkflowError('Record the statement first using a record_statement command')
            tids=[x for x in args.transactions.split(',') if x]
            tx=[repo.transaction(t) for t in tids]
            if any(t is None for t in tx):raise WorkflowError('Unknown transaction')
            difference=st['opening_balance_minor']+sum(t['amount_minor'] for t in tx)-st['closing_balance_minor']
            rid=derive_id('recon',args.statement)
            prior=repo._one('reconciliation',{'reconciliation_id':rid})
            expected=[{'entity':'reconciliation','entity_id':rid,'row_version':prior['row_version']}] if prior else []
            result=app.run('reconcile_statement',{'reconciliation_id':rid,'statement_id':args.statement,
                           'included_transaction_ids':tids,'difference_minor':difference,'recon_status':'balanced' if difference==0 else 'open'},expected)
        elif args.action=='refresh':result=app.refresh(args.as_of)
        elif args.action=='payoff':result=app.payoff(read_json(args.scenario),args.replace)
        elif args.action=='payoff-current':
            from perfin_payoff import from_ledger
            result=app.payoff(from_ledger(app.snapshot(),as_of=args.as_of,monthly_minor=args.monthly_cents),args.replace)
        elif args.action=='statements':result=app.statements(args.as_of,args.period_start,read_json(args.options) if args.options else None)
        elif args.action=='snapshot':
            out=app.path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(json.dumps(app.snapshot(),indent=2),encoding='utf-8');result={'snapshot':str(out)}
        elif args.action=='process-outbox':result=app.process_outbox()
        elif args.action=='backup':
            summary=repo.summary();repo.adapter.close();repo=None
            result={'backup_set':str(backup.create_backup(db,app.path('backups'),summary=summary,acknowledge_location=args.acknowledge_location))}
        elif args.action=='status':result=repo.summary()
        else:raise WorkflowError('Unknown action')
        print(json.dumps(result,indent=2));return 0
    except sqlite3.Error as exc:
        print('PerFin refused: SQLite database operation failed ('+type(exc).__name__+')',file=sys.stderr);return 2
    except (ValueError,OSError,RuntimeError,NotImplementedError) as exc:
        # No raw record text, amounts or statement contents in diagnostic logs.
        print('PerFin refused: '+str(exc),file=sys.stderr);return 2
    finally:
        if repo is not None:repo.adapter.close()


if __name__=='__main__':raise SystemExit(main())
