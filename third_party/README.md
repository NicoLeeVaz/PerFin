# Third-party material

Everything here is small, permissively licensed **text** that was copied as evidence or reference for task 1b ([#3](https://github.com/NicoLeeVaz/PerFin/issues/3)). None of it is a PerFin runtime dependency, and none of it is executed.

| Directory | Upstream at pinned commit | License | Contents |
| --- | --- | --- | --- |
| [self-employed-ledger-ms-access](self-employed-ledger-ms-access/SOURCE.md) | lingxiaoyang/self-employed-ledger-ms-access @ `4065602` | MIT | Import macro module, relationship map and VBA reference list, extracted from the `.accdt` package |
| [financial-dashboard-wealthfinpilot](financial-dashboard-wealthfinpilot/SOURCE.md) | WealthFinPilot/Financial-management-tool @ `a5ad1d0` | MIT | 49-line excerpt of `vba/Automate.bas` (`SplitCSV`, `SafeConvertToNumber`) |

Rules for this tree:

- Every directory needs a verbatim `LICENSE` and a `SOURCE.md` that gives the URL, commit, sha256 of each file and a modification log.
- No `.xlsm`, `.accdb` or `.accdt` binaries, and no populated workbooks.
- Material with an unknown or link-only license, such as the Credit Card Spending Tracker, Vertex42 and Microsoft templates, is listed in [research/reuse/catalog.md](../research/reuse/catalog.md) and is never copied here.
- `python3 -I research/reuse/harness/validate_catalog.py` checks the hashes recorded in `research/reuse/catalog.json` against these files.
