# PerFin execution plan

Updated 2026-11-04. [Live tracker](https://github.com/NicoLeeVaz/PerFin/issues/1).

## Selected direction

**Excel is the user interface; Microsoft Access is the authoritative local data layer.** Installed Python handles parsing and deterministic calculations; thin VBA/Power Query/DAO/ODBC integration is selected based on the existing Office setup. SQLite and complete alternative apps remain historical research, not parallel implementation targets.

Privacy, extensibility and reuse are requirements. Ordinary use must work locally without AI, external bank connections or payment execution. Public source contains only code, empty templates and synthetic examples. Actual financial data, populated workbooks/databases, statement PDFs, logs and backups live outside this public repository and outside sync folders by default.

Current status: research plus an actionable backlog. No production importer, Access database or Excel app has yet been built or runtime-verified in this repository.

## How the numbering works

The number is the wave; the letter is an independent task. **1a, 1b and 1c may run concurrently. Every Wave 1 task must be merged and verified before any Wave 2 task begins.** This rule applies to all lower-numbered waves, not just a task's most obvious dependency. GitHub's issue number (for example #2) is separate from the scheduling code (1a).

The table's initial states are a creation snapshot. The tracker gate evidence and linked PRs are authoritative thereafter. A closed issue or merged PR alone is insufficient. An issue closed as duplicate/not planned does not satisfy its gate unless the tracker records the approved replacement/scope decision and evidence.

| Task | Issue | Output | Initial state |
| --- | --- | --- | --- |
| 1a | [Freeze ledger, import and module contracts](https://github.com/NicoLeeVaz/PerFin/issues/2) | A small versioned contract lets backend, importer and workbook agents build independently. | Ready |
| 1b | [Audit and pin reusable Access, Excel and community assets](https://github.com/NicoLeeVaz/PerFin/issues/3) | A small, licensed starter kit with explicit adopt/adapt/reference-only decisions. | Ready |
| 1c | [Define local privacy boundary and NoPii export contract](https://github.com/NicoLeeVaz/PerFin/issues/4) | A practical privacy specification that keeps ordinary finance work local. | Ready |
| 2a | [Build extensible CSV profiles and reviewed import staging](https://github.com/NicoLeeVaz/PerFin/issues/5) | Different CSV formats become validated preview rows without writing to the ledger. | Blocked |
| 2b | [Build Access backend, controlled writes and reproducible setup](https://github.com/NicoLeeVaz/PerFin/issues/6) | An Access database is the sole source of truth, with atomic imports and auditable updates. | Blocked |
| 2c | [Build Excel shell, refreshable views and module interface](https://github.com/NicoLeeVaz/PerFin/issues/7) | A familiar Excel interface displays accounts, transactions, reconciliation and dashboard views. | Blocked |
| 3a | [Deliver first usable CSV → Access → Excel workflow](https://github.com/NicoLeeVaz/PerFin/issues/8) | First usable milestone: import, review, save, reconcile and refresh local finances. | Blocked |
| 3b | [Build and validate mathematical credit-card payoff engine](https://github.com/NicoLeeVaz/PerFin/issues/9) | Reproducible payoff schedules compare cost and time for the user's strategies. | Blocked |
| 3c | [Build personal statements and net-worth module](https://github.com/NicoLeeVaz/PerFin/issues/10) | Dated personal financial statements combine ledger balances and asset valuations without double counting. | Blocked |
| 4a | [Add interactive Excel payoff planner](https://github.com/NicoLeeVaz/PerFin/issues/11) | Users can compare payoff plans visibly in Excel using the validated engine. | Blocked |
| 4b | [Add Excel personal statements and asset valuation entry](https://github.com/NicoLeeVaz/PerFin/issues/12) | Users can view net worth and maintain dated asset estimates through a separate Excel module. | Blocked |
| 4c | [Add local PDF extraction with mandatory import review](https://github.com/NicoLeeVaz/PerFin/issues/13) | Digital PDF statements can feed the existing staging/review workflow without silent ledger writes. | Blocked |
| 5a | [Verify and package the local Windows release](https://github.com/NicoLeeVaz/PerFin/issues/14) | A reproducible, tested local release that a user can install and operate. | Blocked |

## First useful delivery

**3a / #8 is the first functional milestone:** a person can import CSV, review proposed transactions, commit to Access, reconcile statements, refresh Excel and restore a backup. It can be demonstrated as soon as 3a is verified, while 3b and 3c finish. Wave 4 still waits for the entire Wave 3 gate. PDF arrives in 4c; it does not delay the first CSV milestone. Financial statements are a separate optional module at runtime.

## Ownership and independence

| Task | Owned paths |
| --- | --- |
| 1a | contracts/**; docs/contracts.md |
| 1b | research/reuse/**; third_party/** |
| 1c | docs/privacy/**; config/privacy/** |
| 2a | src/perfin_import/**; tests/import/**; fixtures/import/**; docs/import/** |
| 2b | src/perfin_store/**; access/**; tests/store/**; docs/access/** |
| 2c | excel/core/**; tests/excel_core/**; fixtures/excel_core/**; docs/excel/** |
| 3a | src/perfin_app/**; tests/integration_core/**; scripts/core/**; docs/runbooks/core/**; dependency/project manifests; root .gitignore |
| 3b | src/perfin_payoff/**; tests/payoff/**; fixtures/payoff/**; docs/payoff/** |
| 3c | src/perfin_statements/**; tests/statements/**; fixtures/statements/**; docs/statements/** |
| 4a | excel/payoff/**; tests/excel_payoff/**; docs/runbooks/payoff/** |
| 4b | excel/statements/**; tests/excel_statements/**; docs/runbooks/statements/** |
| 4c | src/perfin_pdf/**; tests/pdf/**; fixtures/pdf/**; docs/runbooks/pdf/** |
| 5a | release/**; scripts/release/**; tests/acceptance/**; docs/GETTING-STARTED.md; root README.md; docs/EXECUTION-PLAN.md |

Same-wave tasks use frozen prior-wave contracts and synthetic mocks, never one another's unmerged implementation. Maintain one active owner per issue and separate branches/worktrees. Payoff and net-worth Excel modules have separate workbook files to prevent binary merge collisions. Do not create a monolithic workbook concurrently.

The coordinator owns tracker updates and gate-evidence updates to this plan. Shared packaging is integrated by 3a. Request shared interface changes through the tracker; pause affected work and revalidate dependent results after a contract change. Do not silently broaden an issue's owned paths. Missing Windows/Office capabilities block applicable runtime checks; they are not evidence of failure in the code, and they are never recorded as passed.

## Gate checklist

- [ ] Wave 1: contracts, reusable-asset decisions and privacy specification are merged, internally consistent and verified. Freeze interface version for Wave 2.
- [ ] Wave 2: CSV staging, Access repository and Excel shell pass their acceptance checks, including required Windows/Office checks. Independent components conform to the same frozen contract.
- [ ] Wave 3: core end-to-end workflow is usable; payoff and statement engines pass independent mathematical/accounting tests.
- [ ] Wave 4: Excel modules and local PDF staging pass their acceptance checks without changing frozen core interfaces.
- [ ] Wave 5: a fresh Windows installation and complete offline acceptance/backup-restore run pass; release evidence is published.

For each passed gate, the coordinator records issue IDs, merged PRs/commit revisions, commands/results, environment, acceptance evidence and remaining non-blocking limitations in the tracker. Reopen the gate when a prerequisite defect invalidates its evidence. Do not bypass it simply because the next issue is open.

## Agent pickup procedure

1. Read root AGENTS.md, this plan, the tracker and the selected issue. Inspect current repository instructions and uncommitted work.
2. Confirm every lower-wave gate has verified evidence. Select one unclaimed issue from the earliest eligible wave. If none is eligible, report the concrete blocker; do not start later-wave implementation.
3. Claim with agent/session identity and branch in the issue, then create `agent/<code>-<description>` from current main in an isolated worktree. No mass assignment or automated messages to others are needed.
4. Read the exact inherited contracts/research relevant to the task. Implement within owned paths, using synthetic fixtures and local deterministic rules/calculations.
5. Run meaningful acceptance checks. Record executed commands/results and runtime. Mark unrun Windows/Excel/Access checks as pending, with a reproducible handoff.
6. Open a focused PR linked to the issue, with behavior, tests and limitations. The coordinator reviews/merges and records gate evidence. Do not self-declare unrelated tasks done.

## Copy/paste agent prompt

```text
Work in NicoLeeVaz/PerFin. Read AGENTS.md, docs/EXECUTION-PLAN.md,
tracker issue #1 and the current issue/PR state. Pick one unclaimed task
from the earliest eligible wave (or work on the specified task: <code>).
All lower-numbered tasks must be merged and verified before starting.
Claim the issue with your session/branch, use an isolated worktree and
stay within its owned paths. Excel is the frontend; Access is the local
source of truth. Use the frozen contracts and synthetic data only.
Complete the issue's acceptance checks, open a focused PR and report
executed tests, pending Windows/Office checks and exact handoff artifacts.
Do not introduce cloud processing, bank connections, payment execution,
real financial records in Git, or a second authoritative ledger.
If blocked, identify the unmet prerequisite instead of skipping waves.
```

## Research and reuse

[Research index](../research/README.md), [source review](../research/source-review.md) and [payoff/net-worth requirements](../research/payoff-and-net-worth-plan.md) remain supporting evidence. Task 1b turns candidates into a license-checked, pinned starter kit; no downloaded template is presumed production-ready. Free/personal-use templates may be link-only and are not automatically open source. NoPii is an optional export boundary, not a prerequisite for ordinary local imports or a guarantee that an Excel add-in stays local.
