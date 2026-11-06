# Portable SQLite and workbook demonstration

This demonstration runs on Linux, macOS or Windows with the project's Python
dependencies. It creates a real SQLite database, exercises explicit review and
commit, and generates the existing PerFin core, payoff and statements workbooks.
It accepts no user financial files: every transaction and scenario is invented.
That makes it suitable for a cloud development environment without uploading
private account data. No application network access is required.

From the repository checkout, select a new directory outside the checkout and
outside synchronized folders:

```sh
python3 scripts/core/portable_demo.py --out /tmp/perfin-portable-demo
```

Windows equivalent:

```bat
py -3 scripts\core\portable_demo.py --out "%LOCALAPPDATA%\PerFin-portable-demo"
```

The directory must be new or empty. The script refuses existing contents rather
than replacing a database, report, or workbook. Re-run with a different directory.
It uses the production SQLite adapter and repository, not the test-only fake.

## Outputs

| File within the selected output directory | Purpose |
| --- | --- |
| `index.html` | Offline overview with links to the three workbooks and evidence |
| `db/perfin.sqlite` | Real synthetic SQLite ledger, staging, commands, audit and reconciliation history |
| `workbooks/PerFin-Core.xlsx` | Account, card, transaction and reconciliation views |
| `workbooks/excel_payoff/PerFin-Payoff.xlsx` | Two strategy comparisons for the zero-APR illustration |
| `workbooks/excel_statements/PerFin-Statements.xlsx` | Net worth, income, cash flow, bridge and valuation-entry views |
| `reports/*.csv` | Contract report tables consumed by the workbook generators |
| `portable-demo-evidence.json` | Explicit check results, native-test status and SHA-256 hashes for each XLSX |

The data directory marker records `kind: synthetic` and `backend: sqlite`.
The SQLite file is authoritative. XLSX files and CSV reports are snapshots,
and editing a workbook cell does not silently change the ledger.

## What the run proves

The example creates six reviewed CSV imports across two statement cycles for one
checking account and two cards. Before every review, it checks that staging has
not changed the ledger. It then confirms imports, links four transfers and
reconciles six statements. Re-importing each CSV must be a no-op. Finally it
closes and reopens SQLite to verify persisted balances and history.

These expected totals are specified independently of the generated reports:

| Measure | Expected |
| --- | --- |
| Checking | 234000 cents / $2,340.00 |
| Card A balance | -17600 cents / $176.00 owed |
| Card B balance | -6200 cents / $62.00 owed |
| Net worth | 210200 cents / $2,102.00 |
| Transactions / transfers / reconciliations | 16 / 4 / 6 |
| Payoff illustration | $238 at 0% APR with $100/month: 3 months, zero interest |

The payoff assumptions are deliberately simple, synthetic arithmetic. They do
not estimate real card terms. Real scenarios must use their actual APR, minimum
payment rules, fees and supported modeling assumptions.

The run checks the CSV balances, XLSX account values, expected formula text,
worksheet tables, payoff results, and absence of external links and unsafe
workbook content using the project's static offline checker. It does not open
Excel or calculate Excel formulas. Python engines calculate the payoff and
statement values; workbook formulas remain available for Excel to calculate.

## Evidence and release requirements

Exit codes are `0` for a successful portable demonstration, `1` for a failed
step, and `2` for a refused output location or existing directory. Failure after
initialization writes a FAIL evidence record; it never produces the success
overview. The evidence labels native Excel and Access acceptance as PENDING.

Desktop Excel recalculation, Power Query, VBA, native Access/ACE queries and
Office-specific behavior remain release requirements for those integrations.
They do not block SQLite development, generated XLSX previews or Python tests.
Static workbook inspection is not an OS-level offline guarantee for Excel.

Run the real SQLite regression suite for this demonstration:

```sh
python3 -B -W error -m unittest discover -s tests/portable_demo -v
```

The tests also prove refusal before writing existing content, database integrity,
replay persistence and that an injected workbook failure cannot become a PASS.
