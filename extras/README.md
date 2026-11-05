# Optional finance toolbox

Open [the searchable HTML catalog](index.html) locally, or browse [catalog.json](catalog.json). This is a standard, **opt-in** layer of separate tools: the main ledger stays authoritative. It works independently of the current SQLite migration and optional Access backend.

## What is included now

- Source-linked mortgage/amortization/extra-payment, loan comparison, vehicle loan, savings, retirement, budgeting, property and investment-analysis candidates.
- Microsoft's existing financial functions and what-if tools; Microsoft templates; Vertex42; two MIT community projects; Store/vendor add-in research.
- A standalone XLSX inspection and registration helper using the existing PerFin module launcher contract. No core workbook or database is modified.
- Exact-file local review evidence. No third-party template binary is redistributed, auto-downloaded, purchased or installed by this catalog.

The HTML is a local catalog, not a calculator. Downloadable files and native Excel calculations are **not yet certified**. The first practical choices are a mortgage extra-payment template, a loan comparison sheet and a savings-goal calculator. Reuse those before building custom equivalents.

## Download and use privately

1. Follow a publisher link. For Microsoft, choose the named template from the gallery; it may open an online preview. Download/save a **blank** local Excel copy before entering financial information. If no suitable local download is available, keep that candidate online-only, outside PerFin.
2. Check the actual file's terms. Vertex42 personal-use files are not for public redistribution; a commercial-use purchase is not automatically a redistribution license. MIT copies must retain the license/copyright. Reddit posts or shared Sheets have no inferred reuse license.
3. Keep the template and its populated working copy outside Git and sync folders. Do not remove required attribution to pass a scanner. A template with attribution hyperlinks may need to remain a separately reviewed standalone tool rather than be registered.
4. Test invented values and inspect assumptions using [acceptance.md](acceptance.md). Google Sheets exports can lose functions or retain online dependencies; export compatibility is not assumed.

## Make a reviewed local workbook appear in Modules

Use a source checkout with PerFin installed in the active Python environment. These are optional source tools, not a new packaged `perfin extras` command. The helper currently accepts only standalone `.xlsx`, not `.xls`, `.xlsm`, `.xlam`, `.ods`, macros, queries or add-ins.

```bat
python extras\register.py inspect C:\Private\Loan.xlsx
```

Copy `extras/review.example.json` outside the checkout. Enter the returned SHA256, source, license, your environment and actual synthetic/math/offline evidence. Set each check to true **only after observing it**. The tool records these as operator-reported, not independent certification. If any source bytes change, inspect/review them again.

```bat
python extras\register.py register C:\Private\Loan.xlsx --id extra_mortgage_v1 --data-root "%LOCALAPPDATA%\PerFin" --evidence C:\Private\loan-review.json
perfin --data-root "%LOCALAPPDATA%\PerFin" refresh
```

The copy and manifest go to `workbooks/extra_mortgage_v1/`; refresh the core workbook to see it in Modules. It has no report inputs, commands or ledger writes. Enter scenario values manually. Registration does not open the file, contact its publisher, turn on macros or enable an add-in. No overwrite is allowed; use a new reviewed version ID for an update. The workbook's original bytes and attribution stay intact.

The static scanner blocks known problematic features; it is not malware analysis or proof of offline operation. The registrar additionally refuses all connections, embedded code/objects, custom XML and known external references. It may reject otherwise useful publisher workbooks. Those remain standalone candidates, not silently enabled modules. Evidence covers installed bytes; later workbook edits are not continuously monitored or cryptographically enforced by the core launcher.

## Standard optional categories

1. **Mortgage and loans:** amortization, recurring/lump-sum extras, lender comparison, refinance holding-period analysis, auto loans, balloon/interest-only and variable-rate cases where the chosen model explicitly supports them.
2. **Household planning:** budget, sinking funds, emergency reserve and irregular-expense planning.
3. **Savings and retirement:** savings goals, contribution projections, withdrawals, college and inflation scenarios; projections stay separate from the net-worth ledger.
4. **Property and investments:** rental cash-flow/cap-rate/cash-on-cash analysis, NPV/IRR and scenario comparison. No live market feed is needed for manual assumptions.
5. **Online add-ins:** separate explicit choice, not part of the default local workflow. A Store listing is not proof of offline use; inspect permissions, service endpoints, subscription and privacy terms.

## Development sequence

- **E1 (delivered here):** catalog, links, local registration, review evidence and refusal tests.
- **E2 (per selected file):** pin publisher revision/download hash; check license; test formulas and offline desktop behavior; retain evidence locally. Until then no candidate is marked verified or bundled.
- **E3 (later, optional):** add explicit read-only scenario input adapters from current balances. Never import forecast balances as actual ledger entries. Any future valuation/write-back needs the normal reviewed command contract.

Native Excel validation is a release requirement for the selected extra, not a blocker on unrelated development. No architecture or database migration is introduced by E1.

## Checks

```sh
python -m unittest discover -s tests/extras -v
python extras/build_catalog.py
```

Use an environment with PerFin installed. The tests use generated synthetic workbooks, never third-party user data. They verify immutable source copying, manifest/registry compatibility, refusal of stale hashes, missing evidence, macro/connections/network features, overwritten destinations and path escapes. They do not verify a vendor's financial formulas.
