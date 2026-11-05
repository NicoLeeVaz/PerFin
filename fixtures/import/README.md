# Synthetic import fixtures (task 2a)

**Every file in this folder is SYNTHETIC.** The files were written by hand for tests. Merchants, references and amounts are invented. No file comes from, or has been verified against, any real institution's export. No real account or card numbers appear.

| File | Profile | Shows |
| --- | --- | --- |
| `synthetic_checking_signed.csv` | `synthetic_checking_signed` | Signed amounts, a quoted comma and doubled quotes, a quoted CRLF newline, formula-like descriptions, parentheses, thousands separators, a transfer-like payment |
| `synthetic_checking_debit_credit.cp1252.csv` | `synthetic_checking_debit_credit` | Windows-1252 (`É`, `€`), separate debit/credit columns, a trailing empty column |
| `synthetic_card_inverted.csv` | `synthetic_card_inverted` | UTF-8 BOM, inverted card sign, a refund, a payment, interest, two identical purchases with an empty final column |
| `synthetic_checking_malformed.csv` | `synthetic_checking_signed` | Wrong field counts, an invalid amount, a one-decimal amount, an invalid day, an undeclared ISO date, 29 February in a non-leap year |
| `synthetic_eu_semicolon.cp1252.csv` | `profiles/synthetic_eu_semicolon.json` | Worked extension example: a preamble row, a footer, `;`, `DD.MM.YYYY`, `1.234,56` |

The files use CRLF line endings and exact bytes, because their SHA-256 hashes matter. `.gitattributes` marks `*.csv` as `-text` so Git never rewrites them.
