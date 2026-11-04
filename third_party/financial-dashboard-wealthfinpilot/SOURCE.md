# Source: Financial DashBoard / WealthFinPilot (VBA excerpt only)

| Field | Value |
| --- | --- |
| Upstream | <https://github.com/WealthFinPilot/Financial-management-tool> |
| Pinned commit | `a5ad1d023152db1aac67579d5c452c6b9c10107e` (2026-06-06T15:04:46Z, "Rename project from WealthFinPilot to Financial DashBoard") |
| License | MIT, Copyright (c) 2026 Sébastien Oger. Copied verbatim into [LICENSE](LICENSE) |
| Source file | `vba/Automate.bas`: git blob `1789873ea96e38817c3fd5d8958c7385356cbc44`, sha256 `8ac618c059469166ab100112241bac9b7b501f8735fd39a35a11dcb26e88fc11` |
| Retrieved | 2026-11-04 with `git clone https://github.com/WealthFinPilot/Financial-management-tool.git`, followed by a check that HEAD equals the pinned commit |

## Vendored files

| Vendored file | Origin | sha256 |
| --- | --- | --- |
| `Automate.excerpt.bas` | `vba/Automate.bas`, lines 134-182 (`SplitCSV` and `SafeConvertToNumber`) | `0a3687320f862b7e34a4fc316c0c727a7e49dd853d378af79e75f6ce09353d4f` |
| `LICENSE` | repository root `LICENSE` (git blob `ab89678f0dbd53d355d72b985a062dff0a86588d`) | `5305999749e0fa7cc870eb4ffe4d7842c0daa7b0c057abc8505e3aa1abd223b4` |

## Modification log

- 2026-11-04: extracted lines 134-182 of the exported `vba/Automate.bas` with `sed -n 134,182p`. The excerpt was not edited. The rest of the file and the `.xlsm` workbook are **not** vendored.

## Caveats

- The exported `vba/*.bas` files at this commit **differ** from the VBA stored inside `WealthFinPilot_v3.0.xlsm`. In the embedded `Automate` module, `SplitCSV` and `SafeConvertToNumber` match this excerpt, but `ExtractNumber` and the bank-name branches do not. See [`research/reuse/inspection-log.md`](../../research/reuse/inspection-log.md).
- These functions are vendored as **test evidence of the defects** that the port reproduces. They are not intended for reuse, and PerFin should use Python's standard-library `csv` module and exact decimal parsing instead.

## Private-data check

The excerpt contains only generic parsing code, with no names, accounts or amounts.
