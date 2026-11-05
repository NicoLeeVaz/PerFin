-- PerFin Access schema 1.0.0, part 4 of 4: read-only rpt_* report queries for Excel refresh.
-- Columns and their order match contracts/schemas/report_tables.json exactly. Each output
-- column is written "AS [name]" (tests/store/test_schema.py checks the names and order).
-- CREATE VIEW needs ANSI-92 mode (ADO, or ODBC with ExtendedAnsiSQL=1) [Unverified]. If
-- Access rejects a view, setup records contract_meta.report_views = 'partial'; the same SELECT
-- (the text after "AS" on the first line) can be saved as an Access query by hand or with
-- access/setup/PerfinSetup.bas, and `python -m perfin_store export-reports` writes the same
-- tables as CSV in the contract dialect.
-- "As of" is Date() (today). The CSV export takes an explicit --as-of date instead.
-- Known difference: in rpt_review_queue the view's error_codes column holds the stored
-- errors_json text (Access SQL cannot parse JSON); the CSV export holds ';'-joined codes.
-- As of: balances and confirmed payments count only transactions posted on or before the as-of date;
-- statement and card terms are those in effect on it. Listing views (transactions, splits, statements,
-- reconciliation, review queue, card terms, valuations, buckets) have no as-of column and list every row.
-- Rounding: utilization uses Access Round() (half-to-even); the Python export matches it.
-- IIf evaluates both branches: guard the denominator itself against zero.
-- Table names are bracketed in case a name is reserved in Access SQL [Unverified].
-- Nothing here writes: refresh is read-only.

CREATE VIEW rpt_accounts AS SELECT
  a.account_id AS [account_id],
  a.display_name AS [display_name],
  a.kind AS [kind],
  a.account_class AS [account_class],
  a.currency AS [currency],
  a.opening_balance_minor + IIf(IsNull(b.total_minor), 0, b.total_minor) AS [ledger_balance_minor],
  IIf(a.kind = 'liability', -1, 1) * (a.opening_balance_minor + IIf(IsNull(b.total_minor), 0, b.total_minor)) AS [display_balance_minor],
  Date() AS [balance_as_of],
  a.include_in_net_worth AS [include_in_net_worth],
  a.liquidity AS [liquidity],
  a.ownership_pct AS [ownership_pct],
  a.legal_liability_pct AS [legal_liability_pct],
  a.tax_status AS [tax_status]
FROM [account] AS a LEFT JOIN (
  SELECT t.account_id, SUM(t.amount_minor) AS total_minor
  FROM [ledger_txn] AS t WHERE t.posted_date <= Date() GROUP BY t.account_id
) AS b ON a.account_id = b.account_id;

CREATE VIEW rpt_transactions AS SELECT
  t.transaction_id AS [transaction_id],
  t.account_id AS [account_id],
  t.posted_date AS [posted_date],
  t.transaction_date AS [transaction_date],
  t.amount_minor AS [amount_minor],
  t.currency AS [currency],
  t.description AS [description],
  t.entry_method AS [entry_method],
  IIf(EXISTS (
    SELECT ri.transaction_id FROM [reconciliation_item] AS ri INNER JOIN [reconciliation] AS r
      ON ri.reconciliation_id = r.reconciliation_id
    WHERE ri.transaction_id = t.transaction_id AND r.recon_status = 'balanced'
  ), True, False) AS [reconciled],
  t.row_version AS [row_version]
FROM [ledger_txn] AS t;

CREATE VIEW rpt_splits AS SELECT
  s.transaction_id AS [transaction_id],
  s.split_id AS [split_id],
  s.split_kind AS [split_kind],
  s.amount_minor AS [amount_minor],
  s.category_id AS [category_id],
  c.category_kind AS [category_kind],
  s.transfer_link_id AS [transfer_link_id]
FROM [split] AS s LEFT JOIN [category] AS c ON s.category_id = c.category_id;

CREATE VIEW rpt_card_status AS SELECT
  q.account_id AS [account_id],
  q.statement_id AS [statement_id],
  -s.closing_balance_minor AS [statement_closing_owed_minor],
  -q.ledger_balance_minor AS [current_owed_minor],
  q.credit_limit_minor AS [credit_limit_minor],
  Round(-q.ledger_balance_minor * 10000 /
      IIf(q.credit_limit_minor = 0, Null, q.credit_limit_minor), 0) AS [utilization_basis_points],
  s.due_date AS [due_date],
  s.minimum_due_minor AS [minimum_due_minor],
  IIf(IsNull(p.paid_minor), 0, p.paid_minor) AS [confirmed_payments_minor],
  IIf(IsNull(q.statement_id), Null,
      IIf(-s.closing_balance_minor - IIf(IsNull(p.paid_minor), 0, p.paid_minor) > 0,
          -s.closing_balance_minor - IIf(IsNull(p.paid_minor), 0, p.paid_minor), 0)) AS [unpaid_statement_minor],
  Date() AS [as_of]
FROM ((
  SELECT a.account_id,
    (SELECT TOP 1 s1.statement_id FROM [statement] AS s1
      WHERE s1.account_id = a.account_id AND s1.period_end <= Date()
      ORDER BY s1.period_end DESC, s1.statement_id DESC) AS statement_id,
    a.opening_balance_minor + IIf(IsNull(
      (SELECT SUM(t.amount_minor) FROM [ledger_txn] AS t WHERE t.account_id = a.account_id AND t.posted_date <= Date())), 0,
      (SELECT SUM(t2.amount_minor) FROM [ledger_txn] AS t2 WHERE t2.account_id = a.account_id AND t2.posted_date <= Date())) AS ledger_balance_minor,
    (SELECT TOP 1 ct.credit_limit_minor FROM [card_terms] AS ct
      WHERE ct.account_id = a.account_id AND ct.effective_from <= Date()
        AND (ct.effective_to IS NULL OR ct.effective_to >= Date())
      ORDER BY ct.effective_from DESC, ct.terms_id DESC) AS credit_limit_minor
  FROM [account] AS a WHERE a.account_class = 'credit_card'
) AS q LEFT JOIN [statement] AS s ON q.statement_id = s.statement_id)
LEFT JOIN (
  SELECT sp.statement_id, SUM(sp.amount_minor) AS paid_minor
  FROM [statement_payment] AS sp INNER JOIN [ledger_txn] AS pt ON sp.transaction_id = pt.transaction_id
  WHERE pt.posted_date <= Date() GROUP BY sp.statement_id
) AS p ON q.statement_id = p.statement_id;

CREATE VIEW rpt_statements AS SELECT
  s.statement_id AS [statement_id],
  s.account_id AS [account_id],
  s.period_start AS [period_start],
  s.period_end AS [period_end],
  s.due_date AS [due_date],
  s.opening_balance_minor AS [opening_balance_minor],
  s.closing_balance_minor AS [closing_balance_minor],
  s.minimum_due_minor AS [minimum_due_minor]
FROM [statement] AS s;

CREATE VIEW rpt_reconciliation AS SELECT
  r.reconciliation_id AS [reconciliation_id],
  r.statement_id AS [statement_id],
  (SELECT COUNT(*) FROM [reconciliation_item] AS ri WHERE ri.reconciliation_id = r.reconciliation_id) AS [included_count],
  r.difference_minor AS [difference_minor],
  r.recon_status AS [recon_status]
FROM [reconciliation] AS r;

CREATE VIEW rpt_review_queue AS SELECT
  sr.batch_id AS [batch_id],
  sr.row_number AS [row_number],
  sr.review_state AS [review_state],
  sr.duplicate_status AS [duplicate_status],
  IIf(sr.errors_json = '[]', Null, sr.errors_json) AS [error_codes],
  sr.parsed_posted_date AS [posted_date],
  sr.parsed_amount_minor AS [amount_minor],
  sr.parsed_description AS [description]
FROM [staging_row] AS sr INNER JOIN [import_batch] AS b ON sr.batch_id = b.batch_id
WHERE b.batch_status IN ('staged', 'approved');

CREATE VIEW rpt_card_terms AS SELECT
  ct.terms_id AS [terms_id],
  ct.account_id AS [account_id],
  bk.bucket_id AS [bucket_id],
  bk.bucket_kind AS [bucket_kind],
  bk.apr AS [apr],
  bk.promo_end_date AS [promo_end_date],
  bk.deferred_interest AS [deferred_interest],
  ct.effective_from AS [effective_from],
  ct.terms_source AS [terms_source],
  ct.effective_to AS [effective_to],
  ct.credit_limit_minor AS [credit_limit_minor],
  ct.min_rule_type AS [min_rule_type],
  ct.min_amount_minor AS [min_amount_minor],
  ct.min_pct AS [min_pct],
  ct.min_floor_minor AS [min_floor_minor],
  bk.post_promo_apr AS [post_promo_apr]
FROM [card_terms] AS ct INNER JOIN [card_apr_bucket] AS bk ON ct.terms_id = bk.terms_id;

CREATE VIEW rpt_valuations AS SELECT
  v.valuation_id AS [valuation_id],
  v.account_id AS [account_id],
  v.as_of AS [as_of],
  v.value_minor AS [value_minor],
  v.currency AS [currency],
  v.valuation_method AS [valuation_method],
  v.valuation_source AS [valuation_source],
  v.cost_basis_minor AS [cost_basis_minor]
FROM [asset_valuation] AS v;

CREATE VIEW rpt_statement_buckets AS SELECT
  sb.statement_id AS [statement_id],
  s.account_id AS [account_id],
  s.period_end AS [period_end],
  sb.bucket_id AS [bucket_id],
  sb.balance_minor AS [balance_minor]
FROM [statement_bucket_balance] AS sb INNER JOIN [statement] AS s ON sb.statement_id = s.statement_id;
