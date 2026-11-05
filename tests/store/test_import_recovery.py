"""Merged CSV importer -> backend recovery, using the TEST-ONLY fake (not ACE)."""
from test_repository import Base, validate_document
from perfin_app.service import ImportView
from perfin_import import builtin_profiles, stage_file


class ImportRecovery(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.ad.close)

    def stage_csv(self, batch_id, records):
        data = ("Date,Description,Amount,Balance,Transaction ID\n" + records).encode()
        profile = builtin_profiles()[("synthetic_checking_signed", "1.0.0")]
        before = self.state()
        doc = stage_file(data, batch_id + ".csv", profile, "chk:main", ImportView(self.repo),
                         batch_id=batch_id, staged_at="2026-07-10T12:00:00Z").document
        self.assertEqual(self.state(), before)  # parsing must not write the ledger
        self.assertEqual(validate_document(doc), [])
        self.ok(self.repo.stage_batch(doc))
        return doc

    def batch_command(self, kind, batch_id, **payload):
        return self.run_cmd(kind, dict(payload, batch_id=batch_id), [self.ev("batch", batch_id)])

    def commit_csv(self, doc):
        return self.batch_command("commit_batch", doc["batch"]["batch_id"],
                                  source_file_sha256=doc["batch"]["source_file_sha256"])

    def test_importer_duplicate_requires_review_then_commits_both_rows(self):
        doc = self.stage_csv("csv.repeat", "07/01/2026,SYNTHETIC FIRST,-50.00,,bank-1\n"
                             "07/02/2026,SYNTHETIC SECOND,-9.00,,bank-1\n")
        self.assertEqual([r["duplicate"]["status"] for r in doc["rows"]], ["none", "possible"])
        before = self.state()
        self.rejected(self.batch_command("approve_rows", "csv.repeat", row_numbers=[1, 2]),
                      "E_DUPLICATE_UNRESOLVED")
        self.assertEqual(self.state(), before)
        self.ok(self.batch_command("resolve_duplicate", "csv.repeat", row_number=2,
                                   resolution="confirmed_distinct"))
        self.ok(self.batch_command("approve_rows", "csv.repeat", row_numbers=[1, 2]))
        self.ok(self.commit_csv(doc))
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 244100)
        self.assertEqual(len(self.repo.export_bundle()["transactions"]), 2)
        self.assertEqual(validate_document(self.repo.export_bundle()), [])

    def test_collision_committed_after_csv_staging_can_be_reviewed_and_retried(self):
        pending = self.stage_csv("csv.pending", "07/02/2026,SYNTHETIC SECOND,-9.00,,bank-1\n")
        self.assertEqual(pending["rows"][0]["duplicate"]["status"], "none")
        self.ok(self.batch_command("approve_rows", "csv.pending", row_numbers=[1]))
        other = self.stage_csv("csv.first", "07/01/2026,SYNTHETIC FIRST,-50.00,,bank-1\n")
        self.ok(self.batch_command("approve_rows", "csv.first", row_numbers=[1]))
        self.ok(self.commit_csv(other))
        before = self.state()
        self.rejected(self.commit_csv(pending), "E_DUPLICATE_UNRESOLVED")
        self.assertEqual(self.state(), before)  # includes versions, audit and command logs
        self.ok(self.batch_command("resolve_duplicate", "csv.pending", row_number=1,
                                   resolution="confirmed_distinct"))
        self.ok(self.commit_csv(pending))
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 244100)
        self.assertEqual(len(self.repo.export_bundle()["transactions"]), 2)
        self.assertEqual(validate_document(self.repo.export_bundle()), [])
        before = self.state()
        replay = self.commit_csv(pending)
        self.assertEqual(replay["result_status"], "replayed")
        self.assertEqual(self.state(), before)
