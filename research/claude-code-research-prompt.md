# Claude Code prompt: PerFin payoff and net-worth research

Copy the text below into Claude Code from the PerFin repository.

---

Work in `NicoLeeVaz/PerFin`. Complete a research and mathematical-validation phase for a local personal finance system. Read the repository's applicable instructions, existing `research/` files, and especially `research/payoff-and-net-worth-plan.md` before starting. Preserve existing work and any uncommitted user changes.

The main interface should be Excel. Access is a serious candidate; local Python/SQLite is an alternative. VBA, Python or JavaScript automation is acceptable. Keep financial processing local. Do not replace this with a cloud product or assume Microsoft Python in Excel runs locally.

**Priority 1 — Credit-card payoff planning**

Compare all of these explicitly:

1. Largest remaining balance first — the user's literal request.
2. Snowball — smallest remaining balance first.
3. Avalanche — highest applicable APR first, the simplified interest-cost baseline.
4. Near-APR hybrid — choose smallest or largest balance within a configurable rate band, and measure the full-schedule cost of that preference.

Do not confuse highest balance with highest APR, highest utilization or highest monthly interest dollars. Explain marginal savings per extra dollar. Use equal starting debts, payment dates and total payment budgets, pay every minimum first, and roll freed payment capacity into other cards. Specify ranking/re-ranking and deterministic ties.

Make “near APR” explicit in percentage points. Research 0, 0.5, 1 and 2 point bands; these are experiments, not user-approved defaults. Compare lifetime interest plus fees and payoff delay against avalanche using identical assumptions. Report dollar/month tradeoffs; user tolerance limits remain unset until supplied. Do not claim avalanche is globally optimal for promotions, deferred interest or other complex terms without proof.

Write a rigorous math specification and a small reproducible reference experiment. Use Decimal/integer cents, explicit rounding and event order. Clearly label APR/12 monthly results as approximations. Research real daily accrual, due dates, changing minimums, grace periods, residual interest, multiple APR buckets, issuer payment-allocation rules, 0% promotion expiry, deferred interest and transfer fees. Unsupported cases must be explicit.

Validate with hand-calculated examples and independent small-case enumeration or optimization, plus conservation/budget invariants. Include equal APRs, zero APRs, large-balance/low-rate versus small-balance/high-rate, near rates, insufficient budget, negative amortization, final-payment spillover, lump sums, promotion deadlines and horizon truncation. Never call a remaining balance paid off. Distinguish proposed tests from executed results.

Inspect actual open-source calculation files, licenses and tests, not just READMEs. Start with the leads in the plan, including `tomithy83/debt-simulator`. Reproduce or reject the noted allocation and reporting concerns. Verify a usable source/license before recommending any fork. Record commit SHAs and whether each candidate was executed. Prefer a small reliable component over adopting a whole application.

**Priority 2 — Optional personal financial statements**

Design a separate module for a dated balance sheet/net worth, income and expenses, cash flow and a reconciled net-worth change bridge. Include retirement/brokerage accounts, real estate, mortgages and other assets/debts. Share account IDs and reconciled ledger balances with the card module. Avoid duplicated balances and conflicting ledgers.

Specify valuation source/date, ownership, liability responsibility, currency, liquidity, cost basis versus current value, and stale/missing information. Prevent double counting account totals and holdings, property and equity, or business equity and underlying assets. Demonstrate that paying principal from included cash is net-worth-neutral, interest is expense, and retirement contributions between included accounts are transfers. Separate gross net worth, possible after-tax estimates and future retirement scenarios. Do not claim regulatory/accounting compliance or retirement sufficiency from a simple balance sheet.

**Deliverables**

Create the five deliverables listed in section F of `research/payoff-and-net-worth-plan.md`, including synthetic fixtures and reproducible experiment instructions. Add links to `research/README.md`. Use primary sources for financial rules and technical claims; label assumptions, proposed designs and remaining unknowns. End with a short recommendation, verified reuse candidates, executed test results and next implementation steps.

This assignment authorizes research documents and isolated calculation experiments, not a production app, payment execution, bank access, account connections or deployment. Use synthetic data only; keep real statements, populated workbooks, databases and credentials outside this public repository. Do not make asset-sale or retirement-withdrawal recommendations. Do not send information to third parties.

Proceed with reasonable documented assumptions without stopping for minor preferences. Ask only for a genuinely blocking decision. Commit the research and experiment work on a dedicated branch if Git is available; do not overwrite unrelated changes or claim remote publication without verifying it. No paid CI is needed: run relevant validation locally.
