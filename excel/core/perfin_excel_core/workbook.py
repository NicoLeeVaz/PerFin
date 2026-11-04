"""Generate the core PerFin workbook from source (openpyxl).

Two outputs share one layout:

* the **template** (no data): every table has its contract header and one empty row,
  and the status table says NOT_REFRESHED. Power Query (excel/core/powerquery) fills
  the tables on Windows after the VBA setup step installs the queries.
* a **snapshot** built from a report folder: the tables hold what a refresh of those
  CSVs produces, using the same rules as the M code. Linux tests use it to check
  totals, status banners and text safety. It is synthetic-only test output.

Money stays integer minor units in every table cell. Only display formulas divide by
100. Text cells are string cells with the '@' format; a value that could start a
formula also gets Excel's quote prefix (the 1c rule), so it is never evaluated.
"""
import datetime as dt

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.workbook.protection import WorkbookProtection
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.table import Table, TableStyleInfo

from . import SHELL_VERSION, _deps, registry, reports, spec

FIXED_TIME = dt.datetime(2026, 1, 1, 0, 0, 0)
MONEY_FMT = '#,##0.00;-#,##0.00;0.00'
DATE_FMT = "yyyy-mm-dd"
DATETIME_FMT = "yyyy-mm-dd hh:mm"
BAD = PatternFill("solid", fgColor="FFC7CE")
GOOD = PatternFill("solid", fgColor="C6EFCE")
WARN = PatternFill("solid", fgColor="FFEB9C")
TITLE = Font(bold=True, size=14)
BOLD = Font(bold=True)

CF_ROWS = 5000

SHEETS = ["Home", "Status", "Accounts", "Cards", "Transactions", "Review", "Reconciliation", "Modules", "Settings"]

# Where each table sits: sheet, header row, first column. rpt_statements and
# rpt_reconciliation are connection-only queries feeding perfin_statement_recon.
TABLE_PLACES = {
    spec.STATUS_TABLE: ("Status", 14, 1),
    "rpt_accounts": ("Accounts", 14, 1),
    "rpt_card_status": ("Cards", 15, 1),
    "rpt_transactions": ("Transactions", 18, 1),
    "rpt_review_queue": ("Review", 17, 1),
    "perfin_statement_recon": ("Reconciliation", 14, 1),
    "perfin_unreconciled_items": ("Reconciliation", 14, 18),
    spec.MODULES_TABLE: ("Modules", 12, 1),
}

T = "perfin_refresh_status"
STATUS_FORMULA = (
    '=IF(B6="","NOT REFRESHED: run PerFin_Refresh; the Status sheet lists each source",'
    'IF(B9>0,"ERROR: "&B9&" of "&B7&" report sources are missing, invalid or stale. '
    'Figures may be old or incomplete (see Status sheet)",'
    'IF(B11>PerFin_StaleDays,"STALE: last refresh is more than "&PerFin_StaleDays&'
    '" days old. Refresh before relying on these figures",'
    'IF(B10<>"yes","ERROR: report sources have different as-of dates","OK"))))'
)

TX = "rpt_transactions"
_TXC = ("{t}[account_id],$D$5,{t}[posted_date],$D$6,{t}[posted_date],$D$7,{t}[description],$D$8"
        .format(t=TX))

# (sheet, row, label, formula or value, number format, defined name)
SUMMARY = [
    ("Status", 3, "Overall", STATUS_FORMULA, None, "PerFin_Status"),
    ("Status", 5, "Data as of (oldest source)",
     '=IF(COUNT({t}[data_as_of])=0,"",MIN({t}[data_as_of]))'.format(t=T), DATE_FMT, "PerFin_DataAsOf"),
    ("Status", 6, "Last refresh (local time)",
     '=IF(COUNT({t}[checked_at])=0,"",MAX({t}[checked_at]))'.format(t=T), DATETIME_FMT, "PerFin_CheckedAt"),
    ("Status", 7, "Expected report sources", len(spec.CORE_SOURCES), "0", "PerFin_ExpectedSources"),
    ("Status", 8, "Sources OK", '=COUNTIFS({t}[status],"OK")'.format(t=T), "0", None),
    ("Status", 9, "Sources with problems", "=B7-B8", "0", "PerFin_SourceProblems"),
    ("Status", 10, "As-of dates consistent",
     '=IF(COUNT({t}[data_as_of])<2,"yes",IF(MAX({t}[data_as_of])=MIN({t}[data_as_of]),"yes","NO"))'.format(t=T),
     None, None),
    ("Status", 11, "Days since last refresh", '=IF(B6="","",TODAY()-INT(B6))', "0", None),

    ("Accounts", 5, "Total assets",
     '=SUMIFS(rpt_accounts[display_balance_minor],rpt_accounts[kind],"asset")/100', MONEY_FMT, "PerFin_TotalAssets"),
    ("Accounts", 6, "Total owed on liabilities (shown positive)",
     '=SUMIFS(rpt_accounts[display_balance_minor],rpt_accounts[kind],"liability")/100', MONEY_FMT,
     "PerFin_TotalOwed"),
    ("Accounts", 7, "Net ledger balance (assets minus owed; not net worth)", "=B5-B6", MONEY_FMT,
     "PerFin_NetBalance"),
    ("Accounts", 8, "Of which owed on credit cards",
     '=SUMIFS(rpt_accounts[display_balance_minor],rpt_accounts[account_class],"credit_card")/100', MONEY_FMT,
     "PerFin_CardsOwed"),
    ("Accounts", 9, "Accounts", "=COUNTA(rpt_accounts[account_id])", "0", "PerFin_AccountCount"),
    ("Accounts", 10, "Check: sum of ledger balances", "=SUM(rpt_accounts[ledger_balance_minor])/100", MONEY_FMT,
     None),
    ("Accounts", 11, "Check: sign convention", '=IF(ROUND(B7-B10,2)=0,"OK","MISMATCH")', None,
     "PerFin_AccountsCheck"),

    ("Cards", 5, "Current owed", "=SUM(rpt_card_status[current_owed_minor])/100", MONEY_FMT, "PerFin_CardCurrentOwed"),
    ("Cards", 6, "Last statement balances owed", "=SUM(rpt_card_status[statement_closing_owed_minor])/100",
     MONEY_FMT, "PerFin_CardStatementOwed"),
    ("Cards", 7, "Minimum due", "=SUM(rpt_card_status[minimum_due_minor])/100", MONEY_FMT, "PerFin_CardMinimumDue"),
    ("Cards", 8, "Confirmed payments", "=SUM(rpt_card_status[confirmed_payments_minor])/100", MONEY_FMT,
     "PerFin_CardPayments"),
    ("Cards", 9, "Unpaid statement balance", "=SUM(rpt_card_status[unpaid_statement_minor])/100", MONEY_FMT,
     "PerFin_CardUnpaid"),
    ("Cards", 10, "Cards with unknown credit limit",
     '=COUNTIFS(rpt_card_status[account_id],"<>",rpt_card_status[credit_limit_minor],"")', "0",
     "PerFin_CardsUnknownLimit"),
    ("Cards", 11, "Utilization of cards with a known limit",
     '=IF(SUMIFS(rpt_card_status[credit_limit_minor],rpt_card_status[credit_limit_minor],"<>")=0,"unknown",'
     'SUMIFS(rpt_card_status[current_owed_minor],rpt_card_status[credit_limit_minor],"<>")/'
     'SUMIFS(rpt_card_status[credit_limit_minor],rpt_card_status[credit_limit_minor],"<>"))', "0.0%",
     "PerFin_CardUtilization"),
    ("Cards", 12, "Next due date", '=IF(COUNT(rpt_card_status[due_date])=0,"",MIN(rpt_card_status[due_date]))',
     DATE_FMT, "PerFin_CardNextDue"),

    ("Transactions", 11, "Matching transactions", "=COUNTIFS(%s)" % _TXC, "0", "PerFin_TxnCount"),
    ("Transactions", 12, "Money in", '=SUMIFS(%s[amount_minor],%s,%s[amount_minor],">0")/100' % (TX, _TXC, TX),
     MONEY_FMT, "PerFin_TxnIn"),
    ("Transactions", 13, "Money out (shown positive)",
     '=-SUMIFS(%s[amount_minor],%s,%s[amount_minor],"<0")/100' % (TX, _TXC, TX), MONEY_FMT, "PerFin_TxnOut"),
    ("Transactions", 14, "Net change", "=SUMIFS(%s[amount_minor],%s)/100" % (TX, _TXC), MONEY_FMT, "PerFin_TxnNet"),
    ("Transactions", 15, "Of which not reconciled", "=COUNTIFS(%s,%s[reconciled],FALSE)" % (_TXC, TX), "0",
     "PerFin_TxnUnreconciled"),

    ("Review", 5, "Rows in review queue", "=COUNTA(rpt_review_queue[batch_id])", "0", "PerFin_ReviewRows"),
    ("Review", 6, "Awaiting review (pending or needs_review)",
     '=COUNTIFS(rpt_review_queue[review_state],"pending")+COUNTIFS(rpt_review_queue[review_state],"needs_review")',
     "0", "PerFin_ReviewAwaiting"),
    ("Review", 7, "Approved, not yet committed", '=COUNTIFS(rpt_review_queue[review_state],"approved")', "0",
     "PerFin_ReviewApproved"),
    ("Review", 8, "Rejected", '=COUNTIFS(rpt_review_queue[review_state],"rejected")', "0", "PerFin_ReviewRejected"),
    ("Review", 9, "Rows with errors", '=COUNTIFS(rpt_review_queue[error_codes],"<>")', "0", "PerFin_ReviewErrors"),
    ("Review", 10, "Possible duplicates to resolve", '=COUNTIFS(rpt_review_queue[duplicate_status],"possible")', "0",
     "PerFin_ReviewPossibleDuplicates"),
    ("Review", 12, "Command drafts folder",
     '=IF(PerFin_DataRoot="","(set on Settings; default %LOCALAPPDATA%\\PerFin)",PerFin_DataRoot&"\\commands\\drafts")',
     None, None),

    ("Reconciliation", 5, "Statements", "=COUNTA(perfin_statement_recon[statement_id])", "0", "PerFin_StatementCount"),
    ("Reconciliation", 6, "Balanced", '=COUNTIFS(perfin_statement_recon[recon_status],"balanced")', "0",
     "PerFin_StatementsBalanced"),
    ("Reconciliation", 7, "Not reconciled or in progress", "=B5-B6", "0", "PerFin_StatementsOpen"),
    ("Reconciliation", 8, "Reconciliations with a non-zero difference",
     '=COUNTIFS(perfin_statement_recon[difference_minor],">0")+COUNTIFS(perfin_statement_recon[difference_minor],"<0")',
     "0", "PerFin_ReconDifferences"),
    ("Reconciliation", 9, "Unreconciled items in statement periods",
     "=COUNTA(perfin_unreconciled_items[transaction_id])", "0", "PerFin_UnreconciledCount"),
    ("Reconciliation", 10, "Net amount of unreconciled items", "=SUM(perfin_unreconciled_items[amount_minor])/100",
     MONEY_FMT, "PerFin_UnreconciledAmount"),
    ("Reconciliation", 11, "Opening balances of listed statements (display sign)",
     "=SUM(perfin_statement_recon[opening_display_minor])/100", MONEY_FMT, "PerFin_StatementOpeningTotal"),

    ("Modules", 5, "Registered modules", "=COUNTA(perfin_modules[module_id])", "0", "PerFin_ModuleCount"),
    ("Modules", 6, "Launchable", "=COUNTIFS(perfin_modules[launchable],TRUE)", "0", "PerFin_ModulesLaunchable"),
    ("Modules", 7, "Invalid or missing", '=COUNTIFS(perfin_modules[module_id],"<>",perfin_modules[status],"<>OK")',
     "0", "PerFin_ModulesInvalid"),
]

HOME_FIGURES = [
    ("Total assets", "=PerFin_TotalAssets", MONEY_FMT),
    ("Total owed on liabilities", "=PerFin_TotalOwed", MONEY_FMT),
    ("Net ledger balance", "=PerFin_NetBalance", MONEY_FMT),
    ("Card minimum due", "=PerFin_CardMinimumDue", MONEY_FMT),
    ("Import rows awaiting review", "=PerFin_ReviewAwaiting", "0"),
    ("Statements not reconciled", "=PerFin_StatementsOpen", "0"),
    ("Unreconciled items", "=PerFin_UnreconciledCount", "0"),
    ("Registered modules", "=PerFin_ModuleCount", "0"),
]

NOTES = {
    "Home": [
        "Read-only view of the PerFin report tables. Access is the only ledger; this workbook never writes it.",
        "Refresh: run macro PerFin_Refresh. Changes: use the Review sheet, which writes command drafts only.",
        "Sheet protection guards against accidental edits. It is not security and not encryption.",
    ],
    "Transactions": [
        "Filters (blank = all). Description uses contains-matching. Table filter buttons also work.",
    ],
    "Review": [
        "Select rows in the table below, then run PerFin_ApproveSelectedRows or PerFin_RejectSelectedRows.",
        "This only writes a command draft. The validator moves it to commands\\outbox; "
        "the PerFin repository applies it.",
    ],
    "Reconciliation": [
        "Opening/closing columns use the ledger sign; *_display_minor shows liabilities as positive owed amounts.",
        "Unreconciled items are transactions in a statement period that no reconciliation includes.",
    ],
    "Modules": [
        "Each module has its own workbook. Select a row and run PerFin_LaunchModule to open it.",
    ],
    "Settings": [
        "Data root must be a local folder outside any Git checkout and outside sync folders (1c privacy boundary).",
        "Power Query reads <data root>\\reports\\*.csv only. No web, cloud, Office Scripts or Python in Excel.",
    ],
}

NOTE_PLACES = {"Transactions": (9, 1), "Review": (13, 1), "Reconciliation": (5, 4), "Modules": (9, 1),
               "Settings": (11, 1)}

INPUT_CELLS = {"Transactions": ["B5", "B6", "B7", "B8"], "Settings": ["B4", "B5", "B6"]}

SETTINGS_NAMES = {"PerFin_DataRoot": "B4", "PerFin_StaleDays": "B5", "PerFin_ModulesDir": "B6",
                  "PerFin_ContractVersion": "B8", "PerFin_ShellVersion": "B9"}


def _fmt(col_type):
    return {"money_minor": "0", "integer": "0", "date": DATE_FMT, "datetime": DATETIME_FMT}.get(col_type, "@")


def set_text(cell, value):
    """Write a text cell that Excel will never evaluate."""
    cell.value = value
    cell.data_type = "s"
    cell.number_format = "@"
    if _deps.needs_formula_escape(value):
        cell.quotePrefix = True  # Excel's stored form of the leading apostrophe (1c rule)


def _set_typed(cell, value, col_type):
    if value is None:
        cell.value = None
        cell.number_format = _fmt(col_type)
    elif col_type in ("id", "text", "enum", "currency", "decimal_string"):
        set_text(cell, str(value))
    else:
        cell.value = value
        cell.number_format = _fmt(col_type)


def _table(ws, name, rows):
    sheet, top, left = TABLE_PLACES[name]
    cols = spec.columns(name)
    for j, (cname, _, _) in enumerate(cols):
        c = ws.cell(row=top, column=left + j)
        set_text(c, cname)
        c.font = BOLD
    body = rows or [{}]
    for i, rec in enumerate(body, start=1):
        for j, (cname, ctype, _) in enumerate(cols):
            _set_typed(ws.cell(row=top + i, column=left + j), rec.get(cname), ctype)
    ref = "%s%d:%s%d" % (get_column_letter(left), top, get_column_letter(left + len(cols) - 1), top + len(body))
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    for j in range(len(cols)):
        letter = get_column_letter(left + j)
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, 14)
    return ref


def _banner(ws):
    ws["A2"] = "Status"
    ws["A3"] = "Data as of"
    ws["B2"] = "=PerFin_Status"
    ws["B3"] = "=PerFin_DataAsOf"
    ws["B3"].number_format = DATE_FMT
    ws["A2"].font = ws["A3"].font = BOLD
    ws.conditional_formatting.add("B2", FormulaRule(formula=['LEFT($B$2,2)<>"OK"'], fill=BAD))
    ws.conditional_formatting.add("B2", FormulaRule(formula=['LEFT($B$2,2)="OK"'], fill=GOOD))


def build(out_path, report_dir=None, modules_dir=None, checked_at=None, stale_days=spec.DEFAULT_STALE_DAYS):
    """Build the core workbook. Without `report_dir` the result is the empty template."""
    if report_dir is None:
        tables = {t: [] for t in spec.CORE_SOURCES + tuple(spec.DERIVED_TABLES)}
        status = reports.not_refreshed_status()
    else:
        if checked_at is None:
            raise ValueError("a snapshot build needs checked_at (the simulated refresh time)")
        tables, status = reports.load_reports(report_dir, checked_at, stale_days)
    tables[spec.STATUS_TABLE] = status
    tables[spec.MODULES_TABLE] = registry.scan(modules_dir) if modules_dir else []

    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: wb.create_sheet(name) for name in SHEETS}
    for name, ws in sheets.items():
        ws["A1"] = "PerFin - " + name
        ws["A1"].font = TITLE
        ws.column_dimensions["A"].width = 48
        ws.column_dimensions["B"].width = 40
        if name not in ("Status", "Settings"):
            _banner(ws)

    for sheet, row, label, formula, fmt, dname in SUMMARY:
        ws = sheets[sheet]
        ws.cell(row=row, column=1, value=label)
        c = ws.cell(row=row, column=2, value=formula)
        if fmt:
            c.number_format = fmt
        if dname:
            wb.defined_names[dname] = DefinedName(dname, attr_text="'%s'!$B$%d" % (sheet, row))
    st = sheets["Status"]
    st["B3"].font = BOLD
    st.conditional_formatting.add("B3", FormulaRule(formula=['LEFT($B$3,2)<>"OK"'], fill=BAD))
    st.conditional_formatting.add("B3", FormulaRule(formula=['LEFT($B$3,2)="OK"'], fill=GOOD))

    for name in TABLE_PLACES:
        sheet = TABLE_PLACES[name][0]
        _table(sheets[sheet], name, tables[name])
    # Highlight rules cover far more rows than the fixtures so they still apply after a refresh grows a table.
    first, last = 15, 14 + CF_ROWS
    st.conditional_formatting.add("C%d:C%d" % (first, last),
                                  FormulaRule(formula=['AND($A%d<>"",$C%d<>"OK")' % (first, first)], fill=BAD))
    top = TABLE_PLACES["rpt_review_queue"][1] + 1
    sheets["Review"].conditional_formatting.add(
        "A%d:H%d" % (top, top + CF_ROWS), FormulaRule(formula=['OR($E%d<>"",$D%d="possible")' % (top, top)], fill=WARN))
    top = TABLE_PLACES["perfin_statement_recon"][1] + 1
    sheets["Reconciliation"].conditional_formatting.add(
        "L%d:L%d" % (top, top + CF_ROWS), FormulaRule(formula=['AND($A%d<>"",$L%d<>"balanced")' % (top, top)], fill=BAD))
    rc = sheets["Reconciliation"]
    rc.cell(row=13, column=1, value="Statements and reconciliation status").font = BOLD
    rc.cell(row=13, column=18, value="Unreconciled items").font = BOLD

    tx = sheets["Transactions"]
    for row, label, crit in [
        (5, "Account id", '=IF(B5="","*",B5)'),
        (6, "Posted from (date)", '=">="&IF(B6="",1,B6)'),
        (7, "Posted to (date)", '="<="&IF(B7="",2958465,B7)'),
        (8, "Description contains", '="*"&B8&"*"'),
    ]:
        tx.cell(row=row, column=1, value=label)
        tx.cell(row=row, column=3, value="criterion")
        tx.cell(row=row, column=4, value=crit)
    tx["B5"].number_format = "@"
    tx["B8"].number_format = "@"
    tx["B6"].number_format = tx["B7"].number_format = DATE_FMT
    tx.column_dimensions["D"].hidden = True

    se = sheets["Settings"]
    for row, label, value in [(4, "Data root (blank = %LOCALAPPDATA%\\PerFin)", None),
                              (5, "Stale after (days)", stale_days),
                              (6, "Modules folder (blank = <data root>\\workbooks)", None),
                              (8, "Contract version", _deps.perfin_contracts.CONTRACT_VERSION),
                              (9, "Core shell version", SHELL_VERSION)]:
        se.cell(row=row, column=1, value=label)
        c = se.cell(row=row, column=2)
        if isinstance(value, str):
            set_text(c, value)
        else:
            c.value = value
    se["B4"].number_format = se["B6"].number_format = "@"
    dv = DataValidation(type="whole", operator="between", formula1="1", formula2="365", allow_blank=False,
                        showErrorMessage=True, error="Whole number of days, 1 to 365")
    se.add_data_validation(dv)
    dv.add("B5")
    for dname, cell in SETTINGS_NAMES.items():
        wb.defined_names[dname] = DefinedName(dname, attr_text="'Settings'!$%s$%s" % (cell[0], cell[1:]))

    home = sheets["Home"]
    for i, (label, formula, fmt) in enumerate(HOME_FIGURES, start=5):
        home.cell(row=i, column=1, value=label)
        home.cell(row=i, column=2, value=formula).number_format = fmt
    nav = 5 + len(HOME_FIGURES) + 1
    home.cell(row=nav, column=1, value="Go to").font = BOLD
    for i, name in enumerate(SHEETS[1:], start=nav + 1):
        c = home.cell(row=i, column=1, value=name)
        c.hyperlink = Hyperlink(ref=c.coordinate, location="'%s'!A1" % name, display=name)
        c.font = Font(underline="single", color="0563C1")

    places = dict(NOTE_PLACES, Home=(nav + len(SHEETS) + 1, 1))
    for name, lines in NOTES.items():
        row, col = places[name]
        for k, line in enumerate(lines):
            set_text(sheets[name].cell(row=row + k, column=col), line)

    for name, ws in sheets.items():
        for coord in INPUT_CELLS.get(name, []):
            ws[coord].protection = Protection(locked=False)
        ws.protection.sheet = True
        ws.protection.autoFilter = False   # allow table filter buttons
        ws.protection.formatColumns = False
        ws.protection.selectLockedCells = False
        ws.protection.selectUnlockedCells = False

    wb.security = WorkbookProtection(lockStructure=True)  # UX guard only; no password
    p = wb.properties
    p.creator = p.lastModifiedBy = "PerFin core shell build %s" % SHELL_VERSION
    p.title = "PerFin core workbook"
    p.created = p.modified = FIXED_TIME
    wb.active = 0
    wb.save(out_path)
    return out_path
