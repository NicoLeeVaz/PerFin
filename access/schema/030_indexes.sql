-- PerFin Access schema 1.0.0, part 3 of 4: secondary indexes.
-- Plain Access DDL. The relationships (foreign keys) are declared in 010_tables.sql; these indexes
-- cover the lookups the repository and the rpt_* report queries make.
-- ux_txn_reverses enforces "a transaction is reversed at most once" in the engine as well as in
-- the repository; WITH IGNORE NULL lets every non-reversal row keep a NULL [Unverified].

CREATE INDEX ix_txn_account_posted ON ledger_txn (account_id, posted_date);
CREATE INDEX ix_txn_source ON ledger_txn (source_batch_id, source_row_number);
CREATE INDEX ix_txn_source_txn_id ON ledger_txn (account_id, source_txn_id);
CREATE UNIQUE INDEX ux_txn_reverses ON ledger_txn (reverses_transaction_id) WITH IGNORE NULL;
CREATE INDEX ix_split_txn ON split (transaction_id);
CREATE INDEX ix_split_category ON split (category_id);
CREATE INDEX ix_split_link ON split (transfer_link_id);
CREATE INDEX ix_link_from ON transfer_link (from_transaction_id);
CREATE INDEX ix_link_to ON transfer_link (to_transaction_id);
CREATE INDEX ix_batch_status ON import_batch (batch_status);
CREATE INDEX ix_staging_fingerprint ON staging_row (fingerprint);
CREATE INDEX ix_statement_account_end ON statement (account_id, period_end);
CREATE INDEX ix_sp_statement ON statement_payment (statement_id);
CREATE INDEX ix_sp_txn ON statement_payment (transaction_id);
CREATE INDEX ix_recon_statement ON reconciliation (statement_id);
CREATE INDEX ix_ri_txn ON reconciliation_item (transaction_id);
CREATE INDEX ix_terms_account ON card_terms (account_id, effective_from);
CREATE INDEX ix_valuation_account ON asset_valuation (account_id, as_of);
CREATE INDEX ix_command_issued ON command_log (issued_at);
CREATE INDEX ix_audit_command ON audit_log (command_id);
CREATE INDEX ix_audit_entity ON audit_log (entity, entity_id);
