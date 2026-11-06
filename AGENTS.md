# PerFin agent instructions

Read [the execution plan](docs/EXECUTION-PLAN.md), [tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1) and your assigned issue before implementation.

- **User architecture decision, 2026-11-05:** SQLite is the default portable local database. Access is an explicit optional backend and future port target. This supersedes earlier Access-only instructions.
- **Native acceptance is a release requirement, not a development gate.** Windows/ACE, desktop Excel, Power Query and VBA stay pending until actually run. They do not block independent development, real SQLite verification or portable packaging.
- Waves 1–5 have merged source. New waves are 6 (data foundation), 7 (portable workflow), 8 (verification/release). Same-wave letters are parallel assignments. Follow declared code dependencies, not blanket lower-wave native gates; scaffolding may use agreed interfaces, but integration must run against the real dependency.
- Use isolated branches/worktrees and explicit ownership. Coordinate shared interfaces and avoid overlapping edits. The coordinator integrates, tests, publishes and reconciles tracker evidence.
- Preserve contract 1.0.1, exact integer minor units, explicit review, auditable commands and one authoritative backend per data root. Never silently switch an existing Access root to SQLite or maintain two writable ledgers.
- Map schema types, collation, constraints, transaction/locking behavior, report SQL and backup deliberately. Identical table names do not prove Access portability. Full-history portability includes staging, audit/command logs and versions.
- Ordinary finance stays local; cloud demonstrations and public fixtures use synthetic data only. Actual statements, databases (including SQLite journals/WAL), populated workbooks, backups, logs, credentials and private NoPii code remain outside the public checkout.
- Test real SQLite files for portable storage behavior. Fake-adapter results are separate evidence. Generated OOXML/formula inspection is not native Excel recalculation.
- Keep source/license attribution and privacy controls. No bank connections, payment execution, telemetry or external AI fallback. No paid hosted CI is required.
- Record exact commands, results, tested revision and environment. Never call a platform release-ready based only on a different platform's tests.
