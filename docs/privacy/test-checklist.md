# Privacy test checklist

Task 1c ([#4](https://github.com/NicoLeeVaz/PerFin/issues/4)). Status values: **passed (Linux)** = executed on Linux with synthetic data, as recorded below; **pending** = not yet run; **owner** = the task expected to run or implement it. A Windows/Office/Access check is never marked passed until it has been run on a real Windows machine, with the Office build and bitness recorded.

Linux reference tests: `cd config/privacy && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v` (34 tests, standard library only). Last run: 2026-11-04, Python 3.13.18 on Linux, all passed. These test the reference rules in [`perfin_privacy_checks.py`](../../config/privacy/perfin_privacy_checks.py), not the eventual application.

## Configuration and contract

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| C1 | `defaults.json` parses; every outbound path O1–O16 has `default_enabled: false`; O2/O3/O8 prohibited; raw fallback false; NoPii not required for core use | passed (Linux) | 1c |
| C2 | Synthetic envelope examples validate against `nopii-export-envelope.schema.json` | passed (Linux) | 1c |
| C3 | Envelope field names (`amount_minor`, `currency`, `date`, ids) reconciled with the 1a contract | pending (Wave 1 gate) | coordinator |

## Spreadsheet formula injection

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| F1 | Text beginning with `=`, `+`, `-`, `@`, tab, carriage return is escaped with `'`; conservative extras (line feed, full-width `＝＋－＠`, leading spaces before a trigger) also escaped; ordinary text unchanged | passed (Linux) | 1c |
| F2 | CSV/outbox export escapes text fields and leaves integer amount columns numeric | passed (Linux) | 1c |
| F3 | Importer stores the original text unchanged in staging/Access (no escape written back) | pending | 2a, 2b |
| F4 | Excel views write text fields as text; a synthetic row with `=HYPERLINK(...)`, `=cmd|' /C calc'!A0`, `@SUM(A1)`, `+1`, `-1` and tab/CR prefixes displays as literal text after refresh, with no evaluation, link or DDE prompt | pending (Windows/Excel) | 2c, 3a |
| F5 | Same synthetic rows exported to CSV and reopened in Excel display as literal text | pending (Windows/Excel) | 3a |
| F6 | Power Query typed text columns do not evaluate formula-like values | pending (Windows/Excel) | 2c |

## Data location and sync folders

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| D1 | Data root inside a Git checkout is refused (including this repository) | passed (Linux) | 1c |
| D2 | OneDrive (personal and `OneDrive - <org>`), Dropbox, Google Drive (`My Drive`), iCloud (`iCloudDrive`, `Mobile Documents`) path segments and `%OneDrive%` env var produce warn-and-block | passed (Linux, path strings only) | 1c |
| D3 | UNC paths and `Desktop`/`Documents`/`Pictures` produce a warning | passed (Linux, path strings only) | 1c |
| D4 | On the user's Windows machine: `%LOCALAPPDATA%\PerFin` is not synced; Known Folder Move state recorded; virtual sync drive letters checked manually | pending (Windows) | 3a, 5a |
| D5 | Application refuses to start against a refused location and requires acknowledgement for a warned one | pending | 3a |
| D6 | Synthetic/real marker: tests refuse a `real` directory | pending | 2a, 2b, 3a |

## Unsanitized PDF originals and exports

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| P1 | Original PDFs are stored only under `statements\originals` and are never included in an export | pending | 4c |
| P2 | Export preview and documentation state that text scrubbing does not sanitize the original PDF and that sanitized text may remain sensitive | passed (document review) | 1c |
| P3 | Missing, unsupported, non-offline or failing adapter disables export; no raw fallback path exists | passed (Linux, gate logic) | 1c |
| P4 | Changed amount, date, currency, record count or money/date tokens in scrubbed text block the export | passed (Linux) | 1c |
| P5 | Residual card numbers, digit runs, emails and known sensitive values block the export | passed (Linux) | 1c |
| P6 | Integration test against a real NoPii adapter with network disabled (no outbound connections observed) | pending (needs adapter) | user / NoPii owner |
| P7 | Export UI requires explicit action, shows the scrubbed preview and confirmation, and writes only to `exports\outbox` | pending (Windows/Excel) | later export task |

No privacy claim about NoPii is made until P6 passes.

## Logs, temp files and retention

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| L1 | Redaction backstop removes card numbers, long digit runs, SSN, email, IBAN and user-profile paths while keeping row numbers and dates | passed (Linux) | 1c |
| L2 | Importer/backend log only allow-listed structured fields; a synthetic import with sensitive-looking descriptions produces logs with none of them | pending | 2a, 2b |
| L3 | Malformed-row errors log row number, field and error code, never the value (including exception text) | pending | 2a |
| L4 | PerFin temp files are created only in `<data root>\temp` and removed at end of run and start-up; Office `~$` and `.laccdb` files are absent after close | pending (Windows) | 2b, 3a |
| L5 | Retention: staging 30 days, outbox 7 days, logs 90 days and 10 MB rotation applied | pending | 3a |
| L6 | AutoRecover location is local and not synced; recorded on the user's machine | pending (Windows/Office) | 5a |
| L7 | Recent-file names and data file names contain aliases/hashes only, no account numbers | pending | 2a, 3a |

## Offline operation and outbound paths

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| N1 | Static scan: PerFin Python has no `socket`, `http`, `urllib`, `requests`, `ftplib`, `smtplib` use; VBA has no `XMLHTTP`, `WinHttp`, `URLDownloadToFile`, `InternetOpen`, `FollowHyperlink`, mail objects or shell calls to network tools | pending (no app code yet) | 2a, 2b, 2c |
| N2 | Full CSV → Access → Excel → backup → restore run with network adapters disabled succeeds | pending (Windows) | 3a, 5a |
| N3 | Workbook inventory: no web Power Query sources, no external workbook links, no `=PY()` cells, no Office Scripts, no bundled add-ins | pending (Windows/Excel) | 2c |
| N4 | Office diagnostic data level, connected experiences and Copilot settings recorded with the minimum chosen | pending (Windows/Office) | 5a |
| N5 | Crash reporting, clipboard history sync and antivirus sample submission settings recorded | pending (Windows) | 5a |

## Backup, restore and encryption

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| B1 | Backup refused while `.laccdb` lock exists; manifest has SHA-256 for every file | pending | 2b |
| B2 | Restore into empty data root verifies hashes and reproduces reconciled balances, import identities and statement history | pending (Windows/Access) | 3a |
| B3 | Backup destination inside a checkout refused; synced/network/removable destinations need acknowledgement and encryption | pending | 3a |
| B4 | Documentation distinguishes BitLocker/EFS/encrypted containers/file passwords from sheet and workbook protection | passed (document review) | 1c |
| B5 | Device encryption state recorded on the user's machine | pending (Windows) | 5a |

## Synthetic-only commits

| # | Check | Status | Owner |
| --- | --- | --- | --- |
| G1 | Repository scan flags `.log`, `.bak`, `.laccdb`, `~$*`, data-dir markers, PDFs/CSV/OFX outside `fixtures/`, Office binaries outside template paths, and Luhn-valid numbers not in the public test list | passed (Linux, synthetic temp repo) | 1c |
| G2 | Scan of this branch finds nothing | passed (Linux) | 1c |
| G3 | Scan wired into a pre-commit hook or release check | pending | 3a, 5a |
| G4 | Every committed fixture is labelled synthetic | pending | 2a, 2c, 3b, 3c, 4c |
