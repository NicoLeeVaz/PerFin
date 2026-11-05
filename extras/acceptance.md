# Optional calculator acceptance

These are PerFin's proposed checks, not claims about a publisher's tested behavior. Record exact input cells, units, expected/actual outputs, calculation mode, version and hash. Use only synthetic values. Do not declare every calculator supports every case.

## Mortgage / loan

- Zero rate: 12,000 principal / 12 end-of-month payments = 1,000 principal per payment, zero interest.
- First-month control: 100,000 at nominal 6% with monthly accrual begins with 500 interest before payment. This check is invalid for a different compounding convention; document the convention.
- For a fully repaid fixed principal loan without new advances, sum of principal equals original principal; closing balance is zero, no negative final debt; final payment is capped. Total payment equals principal plus interest plus included fees.
- A larger extra payment under the same fixed-rate model should not increase remaining interest or payoff time. Test recurring and one-time extras separately; confirm payment dates and prepayment penalties.
- A truncated schedule must report remaining debt. Test zero/negative/blank inputs, short/long terms, non-amortizing payments and the template's maximum row horizon. A date label is not proof of daily interest accrual.
- Distinguish nominal rate, effective rate, compounding interval and payment interval. Do not use APR/12 blindly for every jurisdiction or issuer. P&I excludes taxes/insurance/HOA unless explicitly added.
- For refinancing, compare equal holding periods, closing costs/points, financed costs and remaining balances. Lower monthly payment alone is not savings; a longer term can increase total cost. Simple cost/monthly-savings break-even is only a cash-flow approximation.
- Balloon, variable rates, interest-only periods, escrow and daily simple interest need explicit model support and separate expected cases. Never force them into a plain PMT model.

## Savings / retirement / property

- Zero return: ending savings = starting savings + contributions − withdrawals. Verify beginning/end-of-period timing and inflation treatment.
- Distinguish nominal dollars from real dollars, pre-tax from after-tax, and assumed constant returns from uncertainty. A spreadsheet projection is not a guarantee of retirement sufficiency.
- Tax/account rules can change. Treat tax-specific templates as dated scenarios until current rules are separately checked.
- Rental property: separate operating expenses, reserves, financing principal, interest, tax assumptions and sale proceeds. Do not add both property value and its equity to net worth.
- NPV includes the initial outlay explicitly; IRR can be absent/multiple for changing-sign cash flows. Uneven dates require dated methods rather than pretending equally spaced periods.

## Privacy / file checks

- Inspect formulas, named ranges, hidden sheets, links, queries, add-ins, embedded objects and macros. Keep original license and attribution; no stripping notices for convenience.
- Open in the intended desktop Excel version using only synthetic values. Check recalculation, dates/locale, charts and extreme inputs with network blocked at OS level. A Python static check does not verify Office network behavior.
- Save a final blank/synthetic copy, hash those exact bytes and record review evidence. Any changed formulas/dependencies require new review. A passing built-in function does not certify an entire community workbook.

## Research basis (reviewed 2026-11-05)

- [Microsoft calculator gallery](https://excel.cloud.microsoft/create/en/calculator-templates/): named mortgage, loan, savings, budget and retirement templates. Current gallery emphasizes web use; local-file availability is checked per download.
- [Microsoft PMT](https://support.microsoft.com/en-us/excel/functions/pmt-function): constant rate/payments; payment excludes taxes/reserves/fees.
- [Microsoft IPMT](https://support.microsoft.com/en-us/excel/functions/ipmt-function) and [payments/savings](https://support.microsoft.com/en-us/excel/using-excel-formulas-to-figure-out-payments-and-savings): period and sign consistency.
- [Microsoft what-if tools](https://support.microsoft.com/en-us/excel/introduction-to-what-if-analysis): use existing scenario/goal-seek tools rather than inventing another optimizer.
- [Vertex42 mortgage](https://www.vertex42.com/Calculators/home-mortgage-calculator.html) and [amortization](https://www.vertex42.com/ExcelTemplates/loan-amortization-schedule.html): publisher-described features and personal-use restrictions; downloadable workbooks not audited here.
- [Vertex42 financial directory](https://www.vertex42.com/Calculators/financial-calculators.html): discovery of specialized tools; license/current tax applicability remains per file.
- [My Loan Tracker](https://github.com/DataResearchLabs/my_loan_tracker) and [MIT license](https://github.com/DataResearchLabs/my_loan_tracker/blob/main/LICENSE): inspect/pin the FREE workbook before possible reuse.
- [Home Loan Utilities](https://github.com/lsclark/home-loan-utilities) and [MIT license](https://github.com/lsclark/home-loan-utilities/blob/main/LICENSE): specialized offset/split-loan models; not assumed to match US mortgages.
- [Microsoft Excel add-in architecture](https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-overview): web application plus manifest; may connect to online resources.
- [SaaS Cap Data Store listing](https://appsource.microsoft.com/en-us/product/office/WA200006597): explicit example of document access and Internet capability, kept online-only.
- [Loan Assistant](https://www.add-ins.com/loan_assistant.htm): proprietary vendor add-in candidate; installation/license/runtime not reviewed. No purchase made.

Community Reddit/MrExcel/LibreOffice galleries remain discovery channels, not blanket-approved sources. Retrieve an author's original file, establish the license and validate the actual workbook before promoting it. No credentials or real data are needed for discovery.
