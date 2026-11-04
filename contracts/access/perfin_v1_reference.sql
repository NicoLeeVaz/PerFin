-- PerFin contract 1.0.0: REFERENCE Access DDL (unexecuted).
-- Status: not run on Windows/Access in this task. Task 2b owns the real setup script and must
-- execute and verify it (ANSI-92 mode / ADO is needed for CHECK constraints; DAO ANSI-89 DDL
-- cannot create them). Statements are separated by ';' and use only CREATE TABLE.
-- Money: *_minor columns are CURRENCY holding the INTEGER count of minor units (cents),
-- never major units. Repository code rejects fractional values; CHECK shown where supported.
-- Rates: TEXT decimal strings, as in the JSON contract. Dates: DATETIME with no time part.
-- "transaction" is reserved in Access SQL, so the table is ledger_txn.

CREATE TABLE account (
  account_id TEXT(64) NOT NULL CONSTRAINT pk_account PRIMARY KEY,
  kind TEXT(16) NOT NULL,
  account_class TEXT(24) NOT NULL,
  display_name TEXT(120) NOT NULL,
  institution_alias TEXT(60),
  number_hint TEXT(4),
  currency TEXT(3) NOT NULL,
  opening_balance_minor CURRENCY NOT NULL,
  opening_balance_date DATETIME NOT NULL,
  closed_date DATETIME,
  liquidity TEXT(16),
  ownership_pct INTEGER,
  legal_liability_pct INTEGER,
  include_in_net_worth YESNO,
  tax_status TEXT(16),
  row_version LONG NOT NULL,
  CONSTRAINT ck_account_kind CHECK (kind IN ('asset','liability')),
  CONSTRAINT ck_account_open_int CHECK (opening_balance_minor = Int(opening_balance_minor))
);

CREATE TABLE category (
  category_id TEXT(64) NOT NULL CONSTRAINT pk_category PRIMARY KEY,
  name TEXT(120) NOT NULL,
  category_kind TEXT(16) NOT NULL,
  parent_category_id TEXT(64) CONSTRAINT fk_category_parent REFERENCES category (category_id),
  CONSTRAINT ck_category_kind CHECK (category_kind IN ('income','expense','interest','fee'))
);

CREATE TABLE import_batch (
  batch_id TEXT(64) NOT NULL CONSTRAINT pk_import_batch PRIMARY KEY,
  profile_id TEXT(64) NOT NULL,
  profile_version TEXT(16) NOT NULL,
  account_id TEXT(64) NOT NULL CONSTRAINT fk_batch_account REFERENCES account (account_id),
  source_file_sha256 TEXT(64) NOT NULL,
  source_file_name TEXT(200) NOT NULL,
  staged_at DATETIME NOT NULL,
  committed_at DATETIME,
  importer_version TEXT(16) NOT NULL,
  batch_status TEXT(16) NOT NULL,
  row_version LONG NOT NULL,
  CONSTRAINT uq_batch_file UNIQUE (account_id, source_file_sha256)
);

CREATE TABLE staging_row (
  batch_id TEXT(64) NOT NULL CONSTRAINT fk_staging_batch REFERENCES import_batch (batch_id),
  row_number LONG NOT NULL,
  raw_fields_json MEMO NOT NULL,
  parsed_posted_date DATETIME,
  parsed_transaction_date DATETIME,
  parsed_amount_minor CURRENCY,
  parsed_description MEMO,
  source_txn_id TEXT(128),
  fingerprint TEXT(64) NOT NULL,
  errors_json MEMO NOT NULL,
  duplicate_status TEXT(24) NOT NULL,
  matched_transaction_id TEXT(64),
  review_state TEXT(16) NOT NULL,
  proposed_splits_json MEMO,
  CONSTRAINT pk_staging_row PRIMARY KEY (batch_id, row_number)
);

CREATE TABLE ledger_txn (
  transaction_id TEXT(64) NOT NULL CONSTRAINT pk_ledger_txn PRIMARY KEY,
  account_id TEXT(64) NOT NULL CONSTRAINT fk_txn_account REFERENCES account (account_id),
  posted_date DATETIME NOT NULL,
  transaction_date DATETIME,
  amount_minor CURRENCY NOT NULL,
  currency TEXT(3) NOT NULL,
  description MEMO NOT NULL,
  entry_method TEXT(16) NOT NULL,
  source_batch_id TEXT(64) CONSTRAINT fk_txn_batch REFERENCES import_batch (batch_id),
  source_row_number LONG,
  source_txn_id TEXT(128),
  reverses_transaction_id TEXT(64) CONSTRAINT fk_txn_reverses REFERENCES ledger_txn (transaction_id),
  row_version LONG NOT NULL,
  CONSTRAINT ck_txn_amount_int CHECK (amount_minor = Int(amount_minor))
);

CREATE TABLE transfer_link (
  transfer_link_id TEXT(64) NOT NULL CONSTRAINT pk_transfer_link PRIMARY KEY,
  from_transaction_id TEXT(64) NOT NULL CONSTRAINT fk_link_from REFERENCES ledger_txn (transaction_id),
  to_transaction_id TEXT(64) NOT NULL CONSTRAINT fk_link_to REFERENCES ledger_txn (transaction_id),
  link_status TEXT(16) NOT NULL,
  match_evidence MEMO,
  row_version LONG NOT NULL
);

CREATE TABLE split (
  split_id TEXT(64) NOT NULL CONSTRAINT pk_split PRIMARY KEY,
  transaction_id TEXT(64) NOT NULL CONSTRAINT fk_split_txn REFERENCES ledger_txn (transaction_id),
  split_kind TEXT(16) NOT NULL,
  amount_minor CURRENCY NOT NULL,
  category_id TEXT(64) CONSTRAINT fk_split_category REFERENCES category (category_id),
  transfer_link_id TEXT(64) CONSTRAINT fk_split_link REFERENCES transfer_link (transfer_link_id),
  memo MEMO,
  CONSTRAINT ck_split_kind CHECK (split_kind IN ('category','transfer','adjustment'))
);

CREATE TABLE statement (
  statement_id TEXT(64) NOT NULL CONSTRAINT pk_statement PRIMARY KEY,
  account_id TEXT(64) NOT NULL CONSTRAINT fk_statement_account REFERENCES account (account_id),
  period_start DATETIME NOT NULL,
  period_end DATETIME NOT NULL,
  due_date DATETIME,
  opening_balance_minor CURRENCY NOT NULL,
  closing_balance_minor CURRENCY NOT NULL,
  minimum_due_minor CURRENCY,
  interest_charged_minor CURRENCY,
  fees_charged_minor CURRENCY,
  evidence_ref TEXT(200),
  row_version LONG NOT NULL
);

CREATE TABLE statement_bucket_balance (
  statement_id TEXT(64) NOT NULL CONSTRAINT fk_sbb_statement REFERENCES statement (statement_id),
  bucket_id TEXT(64) NOT NULL,
  balance_minor CURRENCY NOT NULL,
  CONSTRAINT pk_statement_bucket_balance PRIMARY KEY (statement_id, bucket_id)
);

CREATE TABLE statement_payment (
  allocation_id TEXT(64) NOT NULL CONSTRAINT pk_statement_payment PRIMARY KEY,
  statement_id TEXT(64) NOT NULL CONSTRAINT fk_sp_statement REFERENCES statement (statement_id),
  transaction_id TEXT(64) NOT NULL CONSTRAINT fk_sp_txn REFERENCES ledger_txn (transaction_id),
  amount_minor CURRENCY NOT NULL
);

CREATE TABLE reconciliation (
  reconciliation_id TEXT(64) NOT NULL CONSTRAINT pk_reconciliation PRIMARY KEY,
  statement_id TEXT(64) NOT NULL CONSTRAINT fk_recon_statement REFERENCES statement (statement_id),
  difference_minor CURRENCY NOT NULL,
  recon_status TEXT(16) NOT NULL,
  row_version LONG NOT NULL
);

CREATE TABLE reconciliation_item (
  reconciliation_id TEXT(64) NOT NULL CONSTRAINT fk_ri_recon REFERENCES reconciliation (reconciliation_id),
  transaction_id TEXT(64) NOT NULL CONSTRAINT fk_ri_txn REFERENCES ledger_txn (transaction_id),
  CONSTRAINT pk_reconciliation_item PRIMARY KEY (reconciliation_id, transaction_id)
);

CREATE TABLE card_terms (
  terms_id TEXT(64) NOT NULL CONSTRAINT pk_card_terms PRIMARY KEY,
  account_id TEXT(64) NOT NULL CONSTRAINT fk_terms_account REFERENCES account (account_id),
  effective_from DATETIME NOT NULL,
  effective_to DATETIME,
  terms_source TEXT(16) NOT NULL,
  credit_limit_minor CURRENCY,
  min_rule_type TEXT(24) NOT NULL,
  min_amount_minor CURRENCY,
  min_pct TEXT(12),
  min_floor_minor CURRENCY,
  row_version LONG NOT NULL
);

CREATE TABLE card_apr_bucket (
  terms_id TEXT(64) NOT NULL CONSTRAINT fk_bucket_terms REFERENCES card_terms (terms_id),
  bucket_id TEXT(64) NOT NULL,
  bucket_kind TEXT(24) NOT NULL,
  apr TEXT(12) NOT NULL,
  promo_end_date DATETIME,
  post_promo_apr TEXT(12),
  deferred_interest YESNO NOT NULL,
  CONSTRAINT pk_card_apr_bucket PRIMARY KEY (terms_id, bucket_id)
);

CREATE TABLE asset_valuation (
  valuation_id TEXT(64) NOT NULL CONSTRAINT pk_asset_valuation PRIMARY KEY,
  account_id TEXT(64) NOT NULL CONSTRAINT fk_valuation_account REFERENCES account (account_id),
  as_of DATETIME NOT NULL,
  value_minor CURRENCY NOT NULL,
  currency TEXT(3) NOT NULL,
  valuation_source TEXT(120) NOT NULL,
  valuation_method TEXT(24) NOT NULL,
  cost_basis_minor CURRENCY,
  row_version LONG NOT NULL
);

CREATE TABLE command_log (
  command_id TEXT(36) NOT NULL CONSTRAINT pk_command_log PRIMARY KEY,
  command_type TEXT(32) NOT NULL,
  issued_at DATETIME NOT NULL,
  issued_by TEXT(64) NOT NULL,
  payload_json MEMO NOT NULL,
  result_status TEXT(16) NOT NULL,
  result_json MEMO NOT NULL
);

CREATE TABLE audit_log (
  audit_id TEXT(64) NOT NULL CONSTRAINT pk_audit_log PRIMARY KEY,
  command_id TEXT(36) NOT NULL CONSTRAINT fk_audit_command REFERENCES command_log (command_id),
  entity TEXT(32) NOT NULL,
  entity_id TEXT(64) NOT NULL,
  action TEXT(16) NOT NULL,
  before_json MEMO,
  after_json MEMO,
  recorded_at DATETIME NOT NULL
);

CREATE TABLE contract_meta (
  meta_key TEXT(64) NOT NULL CONSTRAINT pk_contract_meta PRIMARY KEY,
  meta_value TEXT(255) NOT NULL
);
