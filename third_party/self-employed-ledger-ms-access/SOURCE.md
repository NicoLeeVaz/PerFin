# Source: Self-Employed Ledger for Microsoft Access (text members only)

| Field | Value |
| --- | --- |
| Upstream | <https://github.com/lingxiaoyang/self-employed-ledger-ms-access> |
| Pinned commit | `4065602606602a0781873f7ac05dac67e69f9291` (2019-09-29T04:14:32Z, "Update README.md") |
| License | MIT, Copyright (c) 2019 Ling X. Yang. Copied verbatim into [LICENSE](LICENSE) |
| Container file | `Self-Employed Ledger.accdt`: git blob `de6e4ab9bcc4822a8e21f06ffc90d33006451519`, 71552 bytes, sha256 `a38518f0732751f38c957e7bf4e688d3c3f0cf30d39c647c880a88daea72d827` |
| Retrieved | 2026-11-04 with `git clone https://github.com/lingxiaoyang/self-employed-ledger-ms-access.git`, followed by a check that HEAD equals the pinned commit |

The `.accdt` file is an OPC/ZIP package. We read its members with Python's `zipfile` module, after checking that no member path was absolute or contained `..`. Nothing was opened in Access, and no macro or VBA code was run. **The `.accdt` binary is not vendored.**

## Vendored files

All three are byte-for-byte copies of members of the `.accdt` package.

| Vendored file | Package member | sha256 | Bytes |
| --- | --- | --- | --- |
| `moduleMacro-DoImportCSV.txt` | `template/database/objects/moduleMacro-DoImportCSV.txt` | `cd3930cc596ce141124ed2b20d064442b176c46aa0c7e94e47ad2c7440b5a47a` | 15259 |
| `relationships.xml` | `template/database/relationships.xml` | `2148309d972b1ddcbc5f88585d4bbd4a269392985f73e3928b36d01f7b09e075` | 2618 |
| `vbaReferences.xml` | `template/database/vbaReferences.xml` | `4bcbc8a31bd564ddde823458e4781dac661fd8b2f7035583980408ba637d66e3` | 581 |
| `LICENSE` | repository root `LICENSE` (git blob `94599bef35e8cfba503b60ab38e0ac60806e06ab`) | `729316c055b2fcd481b7c004df8b2ad371911c5458f55e0af4d35c560d4d929e` | 1069 |

## Modification log

- 2026-11-04: copied unchanged and kept the CRLF line endings. Nothing was edited.

## Why these files are vendored

- They are reference inputs for the behavioural port in [`research/reuse/harness/vba_ports.py`](../../research/reuse/harness/vba_ports.py), which reproduces `ParseCSVLine` and the statement-overlap check, and for task 2b's review of the import transaction pattern and table relationships.
- They are **not** PerFin production code. Task 2b builds a fresh backend; see [the catalog](../../research/reuse/catalog.md#access-seed-decision).

## Private-data check

The macro names public Canadian/US financial institutions as import branches (for example Fido, Costco, Desjardins and BMO Harris). It contains no account numbers, transactions or personal data. The table schemas in the package carry no data rows, and the package contains no data XML files.
