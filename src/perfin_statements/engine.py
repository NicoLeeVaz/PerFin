"""Exact-cent management statements over a validated ledger bundle.

A valuation is a whole-account market value at the end of its as-of date.
Subsequent posted activity rolls it forward; cost basis is never added to value.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from perfin_contracts import CONTRACT_VERSION
from perfin_contracts.semantic import validate_document

VALUED_CLASSES = {'retirement', 'brokerage', 'real_estate', 'vehicle', 'business', 'other_asset'}
CASH_CLASSES = {'checking', 'savings', 'cash'}
BOUND = 922337203685477


class StatementError(ValueError):
    """Invalid or ambiguous inputs; callers must obtain corrected data."""


def _day(value):
    if not isinstance(value, str):
        raise StatementError('dates must be ISO YYYY-MM-DD text')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise StatementError('invalid ISO date') from None
    if result.isoformat() != value:
        raise StatementError('dates must be ISO YYYY-MM-DD text')
    return result


def _rounded(value):
    result = int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if abs(result) > BOUND:
        raise StatementError('report amount exceeds contract money range')
    return result


def _rates(base, rates):
    out = {base: Decimal(1)}
    for currency, rate in (rates or {}).items():
        if not isinstance(rate, str):
            raise StatementError('FX rates must be positive decimal strings')
        try:
            amount = Decimal(rate)
        except InvalidOperation:
            raise StatementError('invalid FX rate') from None
        if not amount.is_finite() or amount <= 0 or amount > Decimal('1000000'):
            raise StatementError('FX rate out of range')
        if currency == base and amount != 1:
            raise StatementError('base-currency rate must equal one')
        out[currency] = amount
    return out


def _weight(account, view):
    key = 'legal_liability_pct' if account['kind'] == 'liability' and view == 'legal' else 'ownership_pct'
    return Decimal(str(account.get(key, 100))) / Decimal(100)


def build_report(bundle, **kwargs):
    """Return a frozen-contract net_worth_report. See build_statements for details."""
    return build_statements(bundle, **kwargs)['net_worth']


def build_statements(bundle, *, as_of, period_start, liability_view='legal', fx_rates=None,
                     stale_days=365, inclusion_groups=None):
    """Return net worth, income/expense, cash flow and auditable bridge details.

    fx_rates are constant for both cutoffs and all period flows, not historical
    exchange-rate attribution. Missing FX/valuations exclude affected lines and
    mark the result incomplete. Inclusion groups explicitly identify mutually
    exclusive representations (account total vs holdings, property vs equity).
    """
    if not isinstance(bundle, dict) or bundle.get('document_type') != 'ledger_bundle':
        raise StatementError('expected ledger_bundle')
    errors = validate_document(bundle)
    if errors:
        raise StatementError('ledger fails contract validation: ' + '; '.join(e[0] + ' ' + e[1] for e in errors))
    end, start = _day(as_of), _day(period_start)
    if start > end or start == date.min:
        raise StatementError('period must be ordered and have a preceding opening date')
    if liability_view not in ('legal', 'economic'):
        raise StatementError('liability_view must be legal or economic')
    if isinstance(stale_days, bool) or not isinstance(stale_days, int) or stale_days < 0:
        raise StatementError('stale_days must be a nonnegative integer')
    opening_date = (start - timedelta(days=1)).isoformat()
    accounts = {a['account_id']: a for a in bundle['accounts']}
    groups = inclusion_groups or []
    if not isinstance(groups, list):
        raise StatementError('inclusion_groups must be a list of account-ID lists')
    for group in groups:
        if (not isinstance(group, list) or len(group) < 2
                or not all(isinstance(aid, str) for aid in group) or len(set(group)) != len(group)):
            raise StatementError('each inclusion group needs distinct account IDs')
        if any(aid not in accounts for aid in group):
            raise StatementError('inclusion group references unknown account')
        if sum(accounts[aid].get('include_in_net_worth', True) for aid in group) > 1:
            raise StatementError('overlapping representations: include only one account basis per group')
    rates = _rates(bundle['base_currency'], fx_rates)
    txns = {aid: [] for aid in accounts}
    for txn in bundle['transactions']:
        txns[txn['account_id']].append(txn)
    vals = {aid: [] for aid in accounts}
    for val in bundle.get('asset_valuations', []):
        vals[val['account_id']].append(val)
    for aid, rows in vals.items():
        dates = [v['as_of'] for v in rows]
        if len(dates) != len(set(dates)):
            raise StatementError('multiple valuations for an account on the same date; resolve explicitly')
        if any(v['as_of'] < accounts[aid]['opening_balance_date'] for v in rows):
            raise StatementError('valuation precedes account opening')
    warnings = []
    if fx_rates:
        warnings.append('FX uses supplied constant base-currency rates for both cutoffs and period flows; FX gains are not separated.')
    if liability_view == 'economic':
        warnings.append('Economic liability shares use ownership_pct; legal obligations may be larger.')

    def convert(amount, account):
        with localcontext() as ctx:
            ctx.prec = 48
            return _rounded(Decimal(amount) * rates[account['currency']] * _weight(account, liability_view))

    def snapshot(cutoff):
        lines, detail, basis, incomplete = [], {}, {}, False
        for aid, a in sorted(accounts.items()):
            active = a['opening_balance_date'] <= cutoff
            balance = (a['opening_balance_minor'] + sum(t['amount_minor'] for t in txns[aid]
                       if t['posted_date'] <= cutoff)) if active else 0
            line = dict(account_id=aid, kind=a['kind'], ledger_balance_minor=balance,
                        included_minor=None, valuation_as_of=None, stale=False, excluded_reason=None)
            source = dict(account_id=aid, name=a['display_name'], currency=a['currency'],
                          ownership_pct=a.get('ownership_pct', 100),
                          legal_liability_pct=a.get('legal_liability_pct', 100),
                          liquidity=a.get('liquidity', 'unspecified'), basis='ledger',
                          valuation_source=None, valuation_method=None, cost_basis_minor=None)
            chosen = [v for v in vals[aid] if v['as_of'] <= cutoff]
            val = max(chosen, key=lambda v: v['as_of']) if chosen else None
            raw_value = balance
            if not active or not a.get('include_in_net_worth', True):
                line['excluded_reason'] = 'not_included'
            elif a['currency'] not in rates:
                line['excluded_reason'] = 'missing_fx_rate'
                incomplete = True
            elif val:
                # Whole-account value already contains all activity through its date.
                raw_value = val['value_minor'] + sum(t['amount_minor'] for t in txns[aid]
                            if val['as_of'] < t['posted_date'] <= cutoff)
                line['valuation_as_of'] = val['as_of']
                line['stale'] = (_day(cutoff) - _day(val['as_of'])).days > stale_days
                source.update(basis='valuation_plus_posted_activity', valuation_source=val['valuation_source'],
                              valuation_method=val['valuation_method'], cost_basis_minor=val.get('cost_basis_minor'))
            elif a['account_class'] in VALUED_CLASSES:
                line['excluded_reason'] = 'missing_valuation'
                incomplete = True
            if line['excluded_reason'] is None:
                line['included_minor'] = convert(raw_value, a)
                # Valuation adjustment over ledger basis, including ownership/FX rounding.
                basis[aid] = line['included_minor'] - convert(balance, a)
            else:
                basis[aid] = 0
            if a.get('closed_date') and a['closed_date'] <= cutoff and balance:
                warnings.append('Closed account %s retains a nonzero balance; it remains visible.' % aid)
            detail[aid] = source
            lines.append(line)
        return lines, detail, basis, incomplete

    opening, _, open_basis, open_incomplete = snapshot(opening_date)
    closing, provenance, close_basis, close_incomplete = snapshot(as_of)
    opening_by = {l['account_id']: l for l in opening}
    closing_by = {l['account_id']: l for l in closing}
    for line in closing:
        if line['excluded_reason'] in ('missing_valuation', 'missing_fx_rate'):
            warnings.append('%s: %s; totals are incomplete.' % (line['account_id'], line['excluded_reason']))
        if line['stale']:
            warnings.append('%s: stale valuation rolled forward by posted activity; market movement is unknown.' % line['account_id'])
    if open_incomplete:
        warnings.append('Opening net worth is incomplete; newly available values appear in other change, not earned returns.')
    if not groups:
        warnings.append('No overlap groups supplied: account-total versus holdings/property-equity overlap requires user review.')
    # Income/expense includes category activity in included accounts with known FX.
    kinds = {c['category_id']: c['category_kind'] for c in bundle['categories']}
    names = {c['category_id']: c['name'] for c in bundle['categories']}
    category_totals = {}
    cash = {'income_minor': 0, 'spending_minor': 0, 'interest_minor': 0, 'fees_minor': 0,
            'internal_cash_transfers_minor': 0, 'financing_transfers_minor': 0,
            'investment_transfers_minor': 0, 'other_transfers_minor': 0, 'adjustments_minor': 0}
    links = {l['transfer_link_id']: l for l in bundle.get('transfer_links', [])}
    all_txns = {t['transaction_id']: t for t in bundle['transactions']}
    for txn in bundle['transactions']:
        if not period_start <= txn['posted_date'] <= as_of:
            continue
        a = accounts[txn['account_id']]
        if not a.get('include_in_net_worth', True) or a['currency'] not in rates:
            continue
        for split in txn['splits']:
            amount = convert(split['amount_minor'], a)
            if split['split_kind'] == 'category':
                cid = split['category_id']; kind = kinds[cid]
                category_totals[cid] = category_totals.get(cid, 0) + (amount if kind == 'income' else -amount)
            if a['account_class'] not in CASH_CLASSES:
                continue
            if split['split_kind'] == 'category':
                key = {'income': 'income_minor', 'expense': 'spending_minor', 'interest': 'interest_minor', 'fee': 'fees_minor'}[kind]
                cash[key] += amount  # cash statement signs: inflows positive, outflows negative
            elif split['split_kind'] == 'transfer':
                link = links[split['transfer_link_id']]
                other_id = link['to_transaction_id'] if link['from_transaction_id'] == txn['transaction_id'] else link['from_transaction_id']
                other = accounts[all_txns[other_id]['account_id']]
                if other['account_class'] in CASH_CLASSES and other.get('include_in_net_worth', True):
                    key = 'internal_cash_transfers_minor'
                elif other['kind'] == 'liability':
                    key = 'financing_transfers_minor'
                elif other['account_class'] in VALUED_CLASSES:
                    key = 'investment_transfers_minor'
                else:
                    key = 'other_transfers_minor'
                cash[key] += amount
            else:
                cash['adjustments_minor'] += amount
    income = sum(v for cid, v in category_totals.items() if kinds[cid] == 'income')
    expenses = sum(v for cid, v in category_totals.items() if kinds[cid] != 'income')
    opening_nw = sum(l['included_minor'] or 0 for l in opening)
    closing_nw = sum(l['included_minor'] or 0 for l in closing)
    value_change = sum(close_basis[aid] - open_basis[aid] for aid in accounts
                       if opening_by[aid]['included_minor'] is not None and closing_by[aid]['included_minor'] is not None)
    other = closing_nw - opening_nw - income + expenses - value_change
    bridge_detail = []
    for aid, a in sorted(accounts.items()):
        start_value = opening_by[aid]['included_minor'] or 0
        end_value = closing_by[aid]['included_minor'] or 0
        bridge_detail.append({'account_id': aid, 'opening_minor': start_value, 'closing_minor': end_value,
                              'change_minor': end_value - start_value})
    if other:
        warnings.append('Other change is an unclassified residual requiring review: account setup/inclusion, external transfers, adjustments, missing-value recovery or rounding.')
    report = dict(contract='perfin', contract_version=CONTRACT_VERSION, document_type='net_worth_report',
                  as_of=as_of, period_start=period_start, base_currency=bundle['base_currency'], liability_view=liability_view,
                  lines=closing, totals={'net_worth_minor': closing_nw,
                  'liquid_net_worth_minor': sum(l['included_minor'] or 0 for l in closing
                  if accounts[l['account_id']].get('liquidity') == 'liquid')},
                  bridge={'opening_net_worth_minor': opening_nw, 'income_minor': income, 'expenses_minor': expenses,
                  'valuation_change_minor': value_change, 'other_change_minor': other, 'closing_net_worth_minor': closing_nw},
                  warnings=sorted(set(warnings)))
    errors = validate_document(report)
    if errors:
        raise StatementError('generated report exceeds contract: ' + '; '.join(e[0] + ' ' + e[1] for e in errors))
    cash_accounts = [aid for aid, a in accounts.items() if a['account_class'] in CASH_CLASSES]
    cash_open = sum(opening_by[aid]['included_minor'] or 0 for aid in cash_accounts)
    cash_close = sum(closing_by[aid]['included_minor'] or 0 for aid in cash_accounts)
    cash_activity = sum(cash.values())
    cash.update(opening_cash_minor=cash_open, closing_cash_minor=cash_close,
                setup_valuation_and_rounding_minor=cash_close - cash_open - cash_activity)
    cash['arithmetic_difference_minor'] = cash_close - cash_open - cash_activity - cash['setup_valuation_and_rounding_minor']
    assets = sum(max(l['included_minor'] or 0, 0) for l in closing)
    liabilities = -sum(min(l['included_minor'] or 0, 0) for l in closing)
    return {'net_worth': report, 'complete': not (open_incomplete or close_incomplete),
            'assets_minor': assets, 'liabilities_minor': liabilities,
            'income_expense': {'income_minor': income, 'expenses_minor': expenses, 'surplus_minor': income - expenses,
            'categories': [{'category_id': cid, 'name': names[cid], 'kind': kinds[cid], 'amount_minor': value}
                           for cid, value in sorted(category_totals.items())]},
            'cash_flow': cash, 'provenance': list(provenance.values()), 'bridge_accounts': bridge_detail,
            'basis': 'Personal management statements; gross values, no retirement sufficiency or tax projection.'}
