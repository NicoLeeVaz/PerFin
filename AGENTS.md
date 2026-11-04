# PerFin agent instructions

Read [docs/EXECUTION-PLAN.md](docs/EXECUTION-PLAN.md), [tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1) and the assigned issue before implementation.

- The scheduling code is a wave number plus task letter: 1a, 1b, etc. Tasks in the same wave are independent. Every lower-numbered wave must have merged work and verified acceptance evidence before you start. Closed issues alone do not pass a gate.
- Claim one eligible unclaimed issue with your agent/session identity and branch. Use an isolated worktree and `agent/<code>-<description>` branch from current main. Respect existing user work.
- Stay within the issue's owned paths. Use frozen contracts and mocks rather than sibling branches. Escalate shared contract changes through the tracker and revalidate affected gates.
- Excel is the frontend; Access is the single authoritative local data store. Use local deterministic processing. No alternate production database, cloud processing by default, bank connections or payment execution.
- This repo is public: synthetic fixtures only. Actual statements, populated databases/workbooks, logs, backups, credentials and private NoPii source must stay outside it.
- Read relevant research and preserve source/license attribution. Free templates are not automatically redistributable.
- Complete issue acceptance checks and open a focused PR. Report exact commands/results, environment and pending checks. Windows/Office/Access runtime checks cannot be replaced by Linux unit tests or marked passed when unrun.
- The coordinator verifies evidence, merges work and advances tracker gates. No paid hosted CI is required.
