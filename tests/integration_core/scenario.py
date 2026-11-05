"""SYNTHETIC two-cycle acceptance reused by fake tests and the real Windows runner."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT/'src',ROOT/'contracts/python',ROOT/'excel/core',ROOT/'excel/payoff',ROOT/'excel/statements',ROOT/'tests/store'):
    sys.path.insert(0,str(path))
from perfin_app.service import FinanceApp, accepted
from perfin_app.__main__ import demo_bundle
from perfin_import.profiles import profile_from_mapping


def two_cycles(repo, root):
    accepted(repo.import_bundle(demo_bundle(repo.contract_version)))
    accepted(repo.set_default_categories('expenses','income'))
    app=FinanceApp(repo,root)
    batches=[];all_ids={};last_bytes=None
    for month in (2,3):
        for account,amounts in [('chk:main',[-5000,-3000]),('card:a',[-4000,5000,200]),('card:b',[-1000,3000,-100])]:
            profile=profile_from_mapping({'date':'posted_date','text':'description','amount':'amount'},
                        profile_id='synthetic-'+account.replace(':','-'),profile_version='1.0.0',account_class='checking' if account=='chk:main' else 'credit_card',
                        date_format='YYYY-MM-DD',sign_rule='as_is',decimal_separator='.')
            data=('date,text,amount\r\n'+''.join('2026-%02d-%02d,SYNTHETIC %s,%s\r\n'%(month,i+1,account,format(a/100,'.2f'))
                         for i,a in enumerate(amounts))).encode()
            preview=app.import_csv(data,'synthetic.csv',profile,account);bid=preview['document']['batch']['batch_id']
            app.review(bid,approve=[r['row_number'] for r in preview['document']['rows']]);app.commit(bid)
            ids=[t['transaction_id'] for t in repo.export_bundle()['transactions'] if t.get('source',{}).get('batch_id')==bid]
            all_ids[month,account]=ids;batches.append(bid)
            before=repo.summary();assert app.import_csv(data,'synthetic.csv',profile,account)['result_status']=='replayed';assert repo.summary()==before
        app.link_transfer(all_ids[month,'chk:main'][0],all_ids[month,'card:a'][1])
        app.link_transfer(all_ids[month,'chk:main'][1],all_ids[month,'card:b'][1])
        for account,opening,activity in [('chk:main',250000-8000*(month-2),-8000),('card:a',-20000+1200*(month-2),1200),('card:b',-10000+1900*(month-2),1900)]:
            sid='statement-%s-%s'%(month,account)
            app.run('record_statement',{'statement_id':sid,'account_id':account,'period_start':'2026-%02d-01'%month,
                    'period_end':'2026-%02d-28'%month,'opening_balance_minor':opening,'closing_balance_minor':opening+activity})
            app.run('reconcile_statement',{'reconciliation_id':'rec-'+sid,'statement_id':sid,'included_transaction_ids':all_ids[month,account],
                    'difference_minor':0,'recon_status':'balanced'})
    expected={'chk:main':234000,'card:a':-17600,'card:b':-6200}
    assert repo.summary()['account_balances_minor']==expected,repo.summary()
    assert len(repo.summary()['reconciliations'])==6
    return app,expected
