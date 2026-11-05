# Excel payoff planner

The independent `PerFin-Payoff.xlsx` workbook shows strategy cost, remaining debt, payoff dates and a full payment schedule. Its Inputs, Cards and Cash events sheets are editable; historical Access balances are never edited by this workbook. The engine definition is in [the payoff guide](../../payoff/README.md).

## Create and use

After installing PerFin, build from a saved `payoff_scenario` document:

```powershell
python -m perfin_excel_payoff install "$env:LOCALAPPDATA\PerFin\scenarios\plan.json" --data-root "$env:LOCALAPPDATA\PerFin"
```

1. Open the workbook. Review the as-of date, starting debts, terms, budget and comparison results. The supplied repository fixture is synthetic, not a real issuer profile.
2. Edit blue input cells. APR cells use percentages; money uses dollars with exactly two decimals. Cards identify the source statement. A missing actual statement reference must be resolved before treating a synthetic what-if as a verified current-balance plan.
3. Add event rows for a budget `override`, `lump_sum`, `charge` or `fee`. Month 1 is one calendar month after As of. Charges/fees require an existing account ID. Budget events must leave the account blank.
4. Save and close Excel. Run the explicit local recomputation, then reopen:

```powershell
python -m perfin_excel_payoff recompute "$env:LOCALAPPDATA\PerFin\workbooks\excel_payoff\PerFin-Payoff.xlsx" --data-root "$env:LOCALAPPDATA\PerFin"
```

The Plan status formula compares editable cells with the last computed input snapshot. It should show `INPUTS CHANGED: recompute` after edits. Computation happens only through Python, not by formula-generated debt math. The workbook carries charts and native formulas but their execution/appearance on desktop Excel remains **pending Windows acceptance**. Do not rely on a stale result in an engine that has not recalculated the status formula.

A valid scenario can be queued for Access storage without changing posted transactions:

```powershell
python -m perfin_excel_payoff save-command "$env:LOCALAPPDATA\PerFin\workbooks\excel_payoff\PerFin-Payoff.xlsx" --data-root "$env:LOCALAPPDATA\PerFin"
```

The application processes the validated outbox command. This saves assumptions only. It never initiates a payment. Recompute can use `--output` for an explicit second destination; build refuses an existing file. Outputs must be outside the Git checkout and unacknowledged sync/network directories. No output is uploaded.

The install command writes the bundled `module_manifest.json` beside the workbook under `workbooks/excel_payoff`, where the existing core launcher discovers it. Refresh the core registry after installation. The lower-level `build SCENARIO OUTPUT.xlsx` command creates a workbook at an explicitly chosen location without registration. No macro security bypass is needed: the module is `.xlsx`.

## Supported and pending

- One APR bucket per card; simple introductory rate expiration. Multiple buckets/deferred interest remain visible as unsupported, not silently flattened.
- 1,000 card bucket rows and 1,000 cash-event rows. Rejects formulas in editable inputs, subcent amounts, inconsistent repeated-card minimum terms and invalid events.
- Python tests verify edits → scenario → recomputed results against the engine, privacy paths, future charges, registry launch registration and valid save commands. Source-generated XLSX ZIPs contain no macros or external links.
- Pending on actual Windows desktop Excel: open/recalculate; status changes after each input edit; chart/render inspection; module launch; close/recompute/reopen; Access command processing and refreshed read-only balance source. No Office runtime success is claimed.
