-- PerFin Access schema 1.0.0, part 2 of 4: CHECK constraints (ANSI-92 mode only).
-- Access accepts CHECK only in ANSI-92 SQL mode: through ADO/OLE DB, or through the ACE ODBC
-- driver with ExtendedAnsiSQL=1 in the connection string [Unverified]. DAO (ANSI-89) DDL rejects them.
-- The setup command runs each statement on its own. If Access rejects them, setup records
-- contract_meta.check_constraints = 'absent' and the database relies on the documented
-- fallback: the repository (src/perfin_store) validates every one of these rules, and the
-- whole contract, before it writes. It never writes through any other path.
-- The first five constraints are the reference DDL's. The ck_*_int constraints on the other
-- CURRENCY columns extend the reference rule "integer minor units" to every money column.

ALTER TABLE account ADD CONSTRAINT ck_account_kind CHECK (kind IN ('asset','liability'));
ALTER TABLE account ADD CONSTRAINT ck_account_open_int CHECK (opening_balance_minor = Int(opening_balance_minor));
ALTER TABLE category ADD CONSTRAINT ck_category_kind CHECK (category_kind IN ('income','expense','interest','fee'));
ALTER TABLE ledger_txn ADD CONSTRAINT ck_txn_amount_int CHECK (amount_minor = Int(amount_minor));
ALTER TABLE split ADD CONSTRAINT ck_split_kind CHECK (split_kind IN ('category','transfer','adjustment'));

ALTER TABLE staging_row ADD CONSTRAINT ck_staging_parsed_amount_int CHECK (parsed_amount_minor IS NULL OR parsed_amount_minor = Int(parsed_amount_minor));
ALTER TABLE split ADD CONSTRAINT ck_split_amount_int CHECK (amount_minor IS NULL OR amount_minor = Int(amount_minor));
ALTER TABLE statement ADD CONSTRAINT ck_statement_opening_balance_int CHECK (opening_balance_minor IS NULL OR opening_balance_minor = Int(opening_balance_minor));
ALTER TABLE statement ADD CONSTRAINT ck_statement_closing_balance_int CHECK (closing_balance_minor IS NULL OR closing_balance_minor = Int(closing_balance_minor));
ALTER TABLE statement ADD CONSTRAINT ck_statement_minimum_due_int CHECK (minimum_due_minor IS NULL OR minimum_due_minor = Int(minimum_due_minor));
ALTER TABLE statement ADD CONSTRAINT ck_statement_interest_charged_int CHECK (interest_charged_minor IS NULL OR interest_charged_minor = Int(interest_charged_minor));
ALTER TABLE statement ADD CONSTRAINT ck_statement_fees_charged_int CHECK (fees_charged_minor IS NULL OR fees_charged_minor = Int(fees_charged_minor));
ALTER TABLE statement_bucket_balance ADD CONSTRAINT ck_sbb_balance_int CHECK (balance_minor IS NULL OR balance_minor = Int(balance_minor));
ALTER TABLE statement_payment ADD CONSTRAINT ck_sp_amount_int CHECK (amount_minor IS NULL OR amount_minor = Int(amount_minor));
ALTER TABLE reconciliation ADD CONSTRAINT ck_recon_difference_int CHECK (difference_minor IS NULL OR difference_minor = Int(difference_minor));
ALTER TABLE card_terms ADD CONSTRAINT ck_terms_credit_limit_int CHECK (credit_limit_minor IS NULL OR credit_limit_minor = Int(credit_limit_minor));
ALTER TABLE card_terms ADD CONSTRAINT ck_terms_min_amount_int CHECK (min_amount_minor IS NULL OR min_amount_minor = Int(min_amount_minor));
ALTER TABLE card_terms ADD CONSTRAINT ck_terms_min_floor_int CHECK (min_floor_minor IS NULL OR min_floor_minor = Int(min_floor_minor));
ALTER TABLE asset_valuation ADD CONSTRAINT ck_valuation_value_int CHECK (value_minor IS NULL OR value_minor = Int(value_minor));
ALTER TABLE asset_valuation ADD CONSTRAINT ck_valuation_cost_basis_int CHECK (cost_basis_minor IS NULL OR cost_basis_minor = Int(cost_basis_minor));
