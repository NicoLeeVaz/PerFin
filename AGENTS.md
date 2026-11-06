# PerFin agent instructions

Read [the agent activity and handoff log](docs/AGENT-LOG.md), [the execution plan](docs/EXECUTION-PLAN.md), [tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1) and your assigned issue before implementation.

- **Current handoff:** portable waves 6, 7 and 8a merged in PR #33 (`af6a794`). The next task is [#34: Windows SQLite and desktop Excel acceptance](https://github.com/NicoLeeVaz/PerFin/issues/34), intended for local Codex plus the desktop operator. It is not yet claimed or running. Optional Access/ACE remains separately pending in #30. Read the live issue/log for subsequent ownership changes; do not restart completed waves.
- **Agent log discipline:** when claiming work and before handing it off, update `docs/AGENT-LOG.md` with the actual actor/session, environment, issue, branch/revision, owned files, work performed, observed checks, remaining work and next owner. Keep historical entries. Distinguish an intended owner from an agent that actually started, and distinguish automated, operator-observed, reported and unrun evidence. Keep private runtime evidence outside the public repository.

- **User architecture decision, 2026-11-05:** SQLite is the default portable local database. Access is an explicit optional backend and future port target. This supersedes earlier Access-only instructions.
- **Native acceptance is a release requirement, not a development gate.** Windows/ACE, desktop Excel, Power Query and VBA stay pending until actually run. They do not block independent development, real SQLite verification or portable packaging.
- Waves 1–5 and portable waves 6–8a have merged source. Wave 8b is the outstanding native release requirement. Same-wave letters record separate implementation ownership. Follow declared code dependencies, not blanket lower-wave native gates; integration must run against the real dependency.
- Use isolated branches/worktrees and explicit ownership. Coordinate shared interfaces and avoid overlapping edits. The coordinator integrates, tests, publishes and reconciles tracker evidence.
- Preserve contract 1.0.1, exact integer minor units, explicit review, auditable commands and one authoritative backend per data root. Never silently switch an existing Access root to SQLite or maintain two writable ledgers.
- Map schema types, collation, constraints, transaction/locking behavior, report SQL and backup deliberately. Identical table names do not prove Access portability. Full-history portability includes staging, audit/command logs and versions.
- Ordinary finance stays local; cloud demonstrations and public fixtures use synthetic data only. Actual statements, databases (including SQLite journals/WAL), populated workbooks, backups, logs, credentials and private NoPii code remain outside the public checkout.
- Test real SQLite files for portable storage behavior. Fake-adapter results are separate evidence. Generated OOXML/formula inspection is not native Excel recalculation.
- Keep source/license attribution and privacy controls. No bank connections, payment execution, telemetry or external AI fallback. No paid hosted CI is required.
- Record exact commands, results, tested revision and environment. Never call a platform release-ready based only on a different platform's tests.
