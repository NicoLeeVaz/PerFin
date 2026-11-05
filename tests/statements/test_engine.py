import copy
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'contracts/python')]
from perfin_statements import build_report, build_statements, StatementError
from perfin_contracts.semantic import validate_document


def account(aid, cls='checking', balance=0, **kwargs):
    kind = 'liability' if cls in ('mortgage', 'credit_card', 'test:loan') else 'asset'
    a = dict(account_id=aid, kind=kind, account_class=cls, display_name='SYNTHETIC ' + aid,
             currency='USD', opening_balance_minor=balance, opening_balance_date='2026-01-01',
             row_version=1, liquidity='liquid' if cls=='checking' else 'illiquid')
    a.update(kwargs)
    return a


def bundle():
    return dict(contract='perfin', contract_version='1.0.1', document_type='ledger_bundle', base_currency='USD',
                accounts=[account('test:cash', balance=100000), account('test:loan', 'mortgage', -40000)],
                categories=[dict(category_id='salary', name='Salary', category_kind='income'),
                            dict(category_id='interest', name='Interest', category_kind='interest'),
                            dict(category_id='shop', name='Shopping', category_kind='expense')],
                transactions=[], transfer_links=[], asset_valuations=[])


def txn(b, aid, amount, category='shop', day='2026-02-01'):
    tid = 't' + str(len(b['transactions']) + 1)
    t = dict(transaction_id=tid, account_id=aid, posted_date=day, amount_minor=amount, currency='USD',
             description='SYNTHETIC', entry_method='manual', row_version=1,
             splits=[dict(split_id=tid+'.s', split_kind='category', category_id=category, amount_minor=amount)])
    b['transactions'].append(t)
    return t


def transfer(b, source, target, amount, day='2026-02-01'):
    out = txn(b, source, -amount, day=day); inc = txn(b, target, amount, day=day)
    lid = 'link' + str(len(b['transfer_links'])+1)
    b['transfer_links'].append(dict(transfer_link_id=lid, from_transaction_id=out['transaction_id'],
                                  to_transaction_id=inc['transaction_id'], link_status='confirmed'))
    for t in (out, inc):
        t['splits'] = [dict(split_id=t['transaction_id']+'.s', split_kind='transfer', transfer_link_id=lid,
                           amount_minor=t['amount_minor'])]


def valuation(b, aid, amount, day='2026-01-31'):
    b['asset_valuations'].append(dict(valuation_id='v'+str(len(b['asset_valuations'])+1), account_id=aid,
                  as_of=day, value_minor=amount, currency='USD', valuation_source='SYNTHETIC statement',
                  valuation_method='statement'))


def run(b, **kwargs):
    return build_statements(b, as_of='2026-02-28', period_start='2026-02-01', **kwargs)


class Engine(unittest.TestCase):
    def test_principal_neutral_interest_reduces_worth(self):
        b = bundle(); transfer(b, 'test:cash', 'test:loan', 10000); txn(b, 'test:cash', -500, 'interest')
        r = run(b); nw = r['net_worth']
        self.assertEqual(nw['totals']['net_worth_minor'], 59500)
        self.assertEqual(nw['bridge'], dict(opening_net_worth_minor=60000, income_minor=0, expenses_minor=500,
                         valuation_change_minor=0, other_change_minor=0, closing_net_worth_minor=59500))
        self.assertEqual(r['cash_flow']['financing_transfers_minor'], -10000)
        self.assertEqual(r['cash_flow']['interest_minor'], -500)
        self.assertEqual(r['assets_minor']-r['liabilities_minor'],59500)
        self.assertEqual(validate_document(nw), [])

    def test_retirement_transfer_value_rollforward_and_market_gain(self):
        b=bundle(); b['accounts'].append(account('test:ira','retirement'))
        valuation(b,'test:ira',200000); transfer(b,'test:cash','test:ira',10000)
        r=run(b); self.assertEqual(r['net_worth']['totals']['net_worth_minor'],260000)
        self.assertEqual(r['net_worth']['bridge']['other_change_minor'],0)
        self.assertEqual(r['cash_flow']['investment_transfers_minor'],-10000)
        valuation(b,'test:ira',215000,'2026-02-28')
        r=run(b);self.assertEqual(r['net_worth']['bridge']['valuation_change_minor'],5000)
        self.assertEqual(r['net_worth']['bridge']['other_change_minor'],0)
        self.assertEqual(r['net_worth']['totals']['net_worth_minor'],265000)

    def test_ownership_does_not_reduce_legal_mortgage(self):
        b=bundle(); b['accounts'].append(account('test:home','real_estate',ownership_pct=50))
        b['accounts'][1].update(ownership_pct=50, legal_liability_pct=100)
        valuation(b,'test:home',300000)
        legal=run(b);economic=run(b,liability_view='economic')
        self.assertEqual(legal['net_worth']['totals']['net_worth_minor'],210000)
        self.assertEqual(economic['net_worth']['totals']['net_worth_minor'],230000)

    def test_missing_valuation_excludes_and_flags_incomplete(self):
        b=bundle();b['accounts'].append(account('test:home','real_estate',999999))
        r=run(b);self.assertFalse(r['complete'])
        line=next(x for x in r['net_worth']['lines'] if x['account_id']=='test:home')
        self.assertEqual(line['excluded_reason'],'missing_valuation');self.assertIsNone(line['included_minor'])
        self.assertEqual(r['net_worth']['totals']['net_worth_minor'],60000)

    def test_foreign_currency_is_explicitly_refused_by_frozen_contract(self):
        b=bundle();b['accounts'].append(account('test:eur',balance=10001,currency='EUR'))
        with self.assertRaisesRegex(StatementError, 'E_CURRENCY_MISMATCH'):
            run(b)
        with self.assertRaisesRegex(StatementError, 'E_CURRENCY_MISMATCH'):
            run(b,fx_rates={'EUR':'1.25'})
        for bad in [1.25, 'NaN', '-1', 'Infinity', '0']:
            with self.assertRaises(StatementError):run(bundle(),fx_rates={'USD':bad})

    def test_stale_and_future_valuation(self):
        b=bundle();b['accounts'].append(account('test:home','real_estate'));valuation(b,'test:home',100000)
        valuation(b,'test:home',999999,'2026-03-01')
        r=run(b,stale_days=10);line=next(l for l in r['net_worth']['lines'] if l['account_id']=='test:home')
        self.assertTrue(line['stale']);self.assertEqual(line['included_minor'],100000)

    def test_overlap_requires_one_basis(self):
        b=bundle();b['accounts'] += [account('test:total','retirement'),account('test:holding','brokerage')]
        valuation(b,'test:total',50000);valuation(b,'test:holding',50000)
        with self.assertRaises(StatementError):run(b,inclusion_groups=[['test:total','test:holding']])
        b['accounts'][-1]['include_in_net_worth']=False
        r=run(b,inclusion_groups=[['test:total','test:holding']]);self.assertEqual(r['net_worth']['totals']['net_worth_minor'],110000)

    def test_duplicate_valuation_same_date_rejected(self):
        b=bundle();valuation(b,'test:cash',90000);valuation(b,'test:cash',100000)
        with self.assertRaises(StatementError):run(b)

    def test_refund_reduces_expense_and_ignores_future(self):
        b=bundle();txn(b,'test:cash',10000,'salary');txn(b,'test:cash',-2000);txn(b,'test:cash',500)
        txn(b,'test:cash',99999,'salary','2026-03-01')
        r=run(b);self.assertEqual(r['income_expense']['surplus_minor'],8500)
        self.assertEqual(r['net_worth']['totals']['net_worth_minor'],68500)
        self.assertEqual(r['cash_flow']['arithmetic_difference_minor'],0)

    def test_closed_nonzero_debt_remains_included(self):
        b=bundle();b['accounts'][1]['closed_date']='2026-02-01'
        r=run(b);self.assertEqual(r['net_worth']['totals']['net_worth_minor'],60000)
        self.assertTrue(any('nonzero' in w for w in r['net_worth']['warnings']))

    def test_later_account_opening_is_other_not_income(self):
        b=bundle();b['accounts'][0]['opening_balance_date']='2026-02-10'
        r=run(b);self.assertEqual(r['net_worth']['bridge']['opening_net_worth_minor'],-40000)
        self.assertEqual(r['net_worth']['bridge']['other_change_minor'],100000)

    def test_bad_dates_and_input_type(self):
        for start,end in [('2026-03-01','2026-02-01'),('2026-2-01','2026-02-28')]:
            with self.assertRaises(StatementError):build_report(bundle(),period_start=start,as_of=end)
        with self.assertRaises(StatementError):run({'document_type':'command'})

    def test_fractional_ownership_refused_and_half_cent_rounds_explicitly(self):
        b=bundle();b['accounts'][0]['ownership_pct']=50.5
        with self.assertRaises(StatementError):run(b)
        b['accounts'][0]['ownership_pct']=50
        b['accounts'][0]['opening_balance_minor']=101
        r=run(b)
        self.assertEqual(next(l for l in r['net_worth']['lines'] if l['account_id']=='test:cash')['included_minor'],51)

    def test_synthetic_fixture_matches_hand_calculated_bridge(self):
        b=json.loads((ROOT/'fixtures/statements/household.synthetic.json').read_text())
        expected=json.loads((ROOT/'fixtures/statements/expected.synthetic.json').read_text())
        self.assertEqual(run(b)['net_worth']['bridge'],expected)

    def test_does_not_mutate_input(self):
        b=bundle();before=copy.deepcopy(b);run(b);self.assertEqual(b,before)


if __name__=='__main__':unittest.main()
