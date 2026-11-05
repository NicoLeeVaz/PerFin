"""Local workbook generator and explicit valuation command outbox.

Uses the project's existing openpyxl runtime; generated workbooks remain private.
The Python statements engine owns calculations; Excel exposes their reconciliation
and editable valuation requests. Saving an Excel cell never edits Access.
"""
import hashlib
import json
import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill, Alignment, Protection
from openpyxl.workbook.properties import CalcProperties
from perfin_contracts import CONTRACT_VERSION
from perfin_excel_core.commands import check_data_root, _checked_path, write_to_outbox, validate

MONEY = '#,##0.00;[Red](#,##0.00);"-"'
BLUE = '17365D'
INPUT = 'E8F0FF'


def _text(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'
        if value.startswith(('=', '+', '-', '@', '\t', '\r')):
            cell.quotePrefix = True


def _append(ws, values):
    row = ws.max_row + 1
    if ws.max_row == 1 and ws['A1'].value is None:
        row = 1
    for col, value in enumerate(values, 1):
        _text(ws.cell(row, col), value)
    return row


def _table(ws, title, headers, rows):
    ws['A1'] = title
    ws['A1'].font = Font(size=18, bold=True, color=BLUE)
    ws.append([])
    for col, header in enumerate(headers, 1):
        c = ws.cell(3, col, header)
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor=BLUE)
    for values in rows:
        _append(ws, values)
    ws.freeze_panes = 'A4'
    ws.auto_filter.ref = f'A3:{ws.cell(max(ws.max_row, 3), len(headers)).coordinate}'
    ws.sheet_view.showGridLines = False
    for col in range(1, len(headers)+1):
        ws.column_dimensions[ws.cell(3,col).column_letter].width = 24
    ws.column_dimensions['A'].width = 35
    ws.row_dimensions[1].height = 28
    ws.protection.sheet = True
    ws.protection.autoFilter = False
    ws.protection.sort = False
    return ws


def build(details, output_path, *, data_root, acknowledged=False):
    """Write an .xlsx from build_statements output and return its path.

    Both root and destination pass the core privacy guard before any output.
    """
    root = Path(data_root)
    check_data_root(root, acknowledged)
    out = _checked_path(output_path, root, acknowledged)
    if out.suffix.lower() != '.xlsx':
        raise ValueError('statements workbook must use .xlsx')
    report = details['net_worth']
    from perfin_contracts.semantic import validate_document
    if validate_document(report):
        raise ValueError('invalid net_worth_report')
    provenance = {p['account_id']: p for p in details['provenance']}
    wb = Workbook();wb.remove(wb.active)
    wb.calculation = CalcProperties(calcId=0, fullCalcOnLoad=True)
    summary = _table(wb.create_sheet('Summary'), 'Personal financial statements', ['Measure', 'Value'], [])
    _append(summary, ['As of', date.fromisoformat(report['as_of'])]);summary['B4'].number_format='yyyy-mm-dd'
    _append(summary, ['Period start', date.fromisoformat(report['period_start'])]);summary['B5'].number_format='yyyy-mm-dd'
    _append(summary, ['Currency', report['base_currency']])
    _append(summary, ['Liability basis', report['liability_view']])
    _append(summary, ['Coverage', 'Complete supplied data' if details['complete'] else 'INCOMPLETE: inspect Accounts and warnings'])
    _append(summary, ['Assets', details['assets_minor']/100])
    _append(summary, ['Liabilities', details['liabilities_minor']/100])
    _append(summary, ['Net worth', None]); summary['B11']='=B9-B10'
    _append(summary, ['Income', details['income_expense']['income_minor']/100])
    _append(summary, ['Expenses', details['income_expense']['expenses_minor']/100])
    _append(summary, ['Period surplus', None]);summary['B14']='=B12-B13'
    summary.column_dimensions['B'].width=75
    for row in range(9,15):summary.cell(row,2).number_format=MONEY
    _append(summary,['Refresh','Run the local build command again after Access changes. This workbook is a dated snapshot.'])
    _append(summary,['Valuation entry','Fill Valuations, mark Queue=Yes, then run queue-valuations. Access validates commands before saving.'])
    for warning in report['warnings']:
        r=_append(summary,['Review',warning]);summary.cell(r,2).alignment=Alignment(wrap_text=True);summary.row_dimensions[r].height=32
    account_rows=[]
    for line in report['lines']:
        p=provenance[line['account_id']]
        account_rows.append([line['account_id'],p['name'],line['kind'],line['ledger_balance_minor']/100,
            None if line['included_minor'] is None else line['included_minor']/100,
            None if line['valuation_as_of'] is None else date.fromisoformat(line['valuation_as_of']),
            line['excluded_reason'] or ('STALE ESTIMATE' if line['stale'] else 'Included'),
            p['basis'],p['valuation_source'],p['ownership_pct']/100,p['legal_liability_pct']/100,p['liquidity']])
    accounts=_table(wb.create_sheet('Accounts'),'Balances and valuation sources',
        ['Account ID','Name','Kind','Ledger balance','Included value','Valuation date','Status','Basis','Source','Ownership','Legal liability','Liquidity'],account_rows)
    accounts.column_dimensions['B'].width=32;accounts.column_dimensions['H'].width=36
    for row in range(4,accounts.max_row+1):
        for col in (4,5):accounts.cell(row,col).number_format=MONEY
        accounts.cell(row,6).number_format='yyyy-mm-dd'
        for col in (10,11):accounts.cell(row,col).number_format='0%'
    # Formula-led totals use included values, including overdrafts and liability credits.
    last=max(4,accounts.max_row)
    summary['B9']=f'=SUMIF(Accounts!E4:E{last},">0",Accounts!E4:E{last})'
    summary['B10']=f'=-SUMIF(Accounts!E4:E{last},"<0",Accounts!E4:E{last})'
    inc=_table(wb.create_sheet('Income'),'Income and expenses', ['Category','Kind','Amount'],
        [[r['name'],r['kind'],r['amount_minor']/100] for r in details['income_expense']['categories']])
    for r in range(4,inc.max_row+1):inc.cell(r,3).number_format=MONEY
    cf=_table(wb.create_sheet('Cash flow'),'Cash movements (inflows positive)', ['Movement','Amount'],
        [[k.replace('_minor','').replace('_',' '),v/100] for k,v in details['cash_flow'].items()])
    for r in range(4,cf.max_row+1):cf.cell(r,2).number_format=MONEY
    bridge=_table(wb.create_sheet('Bridge'),'Net-worth change', ['Component','Amount'],
        [[k.replace('_minor','').replace('_',' '),v/100] for k,v in report['bridge'].items()])
    for r in range(4,bridge.max_row+1):bridge.cell(r,2).number_format=MONEY
    _append(bridge,['Other change','Unclassified residual: review account setup, transfers, missing values and rounding.'])
    startrow=bridge.max_row+2
    for col,label in enumerate(['Account','Opening','Closing','Change'],1):bridge.cell(startrow,col,label)
    for record in details['bridge_accounts']:
        r=_append(bridge,[record['account_id'],record['opening_minor']/100,record['closing_minor']/100,record['change_minor']/100])
        for col in (2,3,4):bridge.cell(r,col).number_format=MONEY
    form=_table(wb.create_sheet('Valuations'),'Asset valuation requests',
        ['Account ID','As of','Value','Currency','Source','Method','Valuation ID','Existing version','Queue'],[])
    form['A2']='New valuation IDs preserve history; existing IDs require their current row version.'
    form['A2'].alignment=Alignment(wrap_text=True);form.row_dimensions[2].height=30
    for row in range(4,24):
        for col in range(1,10):
            cell=form.cell(row,col);cell.protection=Protection(locked=False);cell.fill=PatternFill('solid',fgColor=INPUT)
        form.cell(row,2).number_format='yyyy-mm-dd';form.cell(row,3).number_format=MONEY
    form.column_dimensions['A'].width=26;form.column_dimensions['E'].width=32
    if accounts.max_row>=4:
        chart=BarChart();chart.title='Included account values';chart.y_axis.title=report['base_currency']
        chart.add_data(Reference(accounts,min_col=5,min_row=3,max_row=accounts.max_row),titles_from_data=True)
        chart.set_categories(Reference(accounts,min_col=1,min_row=4,max_row=accounts.max_row))
        chart.width=22;chart.height=11;summary.add_chart(chart,'D4')
    wb.properties.title='PerFin personal management statements'
    out.parent.mkdir(parents=True,exist_ok=True)
    temp = None
    try:
        # Exclusive random temporary file: never follow a pre-existing temp symlink.
        with tempfile.NamedTemporaryFile(mode='w+b', suffix='.xlsx', prefix='.perfin-',
                                         dir=out.parent, delete=False) as handle:
            temp = Path(handle.name)
            wb.save(handle)
        temp.replace(out)
    finally:
        wb.close()
        if temp is not None and temp.exists():temp.unlink()
    return out


def _date_cell(value):
    if isinstance(value, datetime):return value.date().isoformat()
    if isinstance(value,date):return value.isoformat()
    if isinstance(value,str) and date.fromisoformat(value).isoformat()==value:return value
    raise ValueError('valuation date must be YYYY-MM-DD or an Excel date')


def read_valuation_commands(workbook_path):
    """Read only rows explicitly marked Yes; reject formulas and invalid money."""
    wb=load_workbook(workbook_path,data_only=False,read_only=True)
    try:
        ws=wb['Valuations'];commands=[]
        for row in ws.iter_rows(min_row=4,max_col=9):
            values=[c.value for c in row]
            if str(values[8]).casefold() not in ('yes','true'):continue
            if any(c.data_type=='f' for c in row):raise ValueError('valuation requests cannot contain formulas')
            aid,asof,value,currency,source,method,vid,version,_=values
            try:
                amount=Decimal(str(value))*100
            except InvalidOperation:
                raise ValueError('valuation must be an exact amount') from None
            if not amount.is_finite() or amount != amount.to_integral_value():
                raise ValueError('valuation must have at most two decimal places')
            if isinstance(value,bool):raise ValueError('valuation cannot be boolean')
            asof = _date_cell(asof)
            if vid is None:
                vid = 'val-' + hashlib.sha256(json.dumps([aid, asof]).encode()).hexdigest()[:24]
            payload=dict(valuation_id=vid,account_id=aid,as_of=asof,value_minor=int(amount),
                         currency=currency,valuation_source=source,valuation_method=method)
            expected=[] if version is None else [dict(entity='asset_valuation',entity_id=vid,row_version=version)]
            identity=json.dumps([payload,expected],sort_keys=True,separators=(',',':'))
            command=dict(contract='perfin',contract_version=CONTRACT_VERSION,document_type='command',
                command_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'perfin:valuation:'+hashlib.sha256(identity.encode()).hexdigest())),
                command_type='record_valuation',issued_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                issued_by='excel_statements:valuation',payload=payload,expected_versions=expected)
            validate(command);commands.append(command)
        return commands
    finally:wb.close()


def queue_valuations(workbook_path, *, data_root, acknowledged=False):
    """Validate selected rows then queue immutable commands, without executing them."""
    check_data_root(data_root,acknowledged)
    workbook_path=_checked_path(workbook_path,data_root,acknowledged)
    commands=read_valuation_commands(workbook_path)
    paths=[]
    for command in commands:
        try:paths.append(write_to_outbox(command,data_root,acknowledged))
        except FileExistsError:
            # Stable IDs make unchanged rows safe to requeue; the backend also replays IDs.
            out=_checked_path(Path(data_root)/'commands/outbox'/(command['command_id']+'.json'),data_root,acknowledged)
            old=json.loads(out.read_text(encoding='utf-8'))
            if old.get('payload')!=command['payload'] or old.get('expected_versions')!=command['expected_versions']:
                raise ValueError('existing command differs from requested valuation')
            paths.append(out)
    return paths
