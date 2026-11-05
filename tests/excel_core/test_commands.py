"""Writes leave Excel only as validated command documents in the local data root."""
import datetime as dt
import json
import shutil
import unittest

import _support
from perfin_contracts.semantic import validate_document
from perfin_excel_core import commands, reports

FIXED = dt.datetime(2026, 7, 2, 15, 10, 0, tzinfo=dt.timezone.utc)


class Build(unittest.TestCase):
    def test_approve_matches_contract_example(self):
        example = _support.load_json(_support.REPO / "contracts" / "examples" / "valid" / "command_approve_rows.json")
        doc = commands.build_review_command("approve_rows", "b2026_07_alpha", [1], batch_row_version=1,
                                            issued_at=FIXED, command_id=example["command_id"])
        self.assertEqual(validate_document(example), [])  # Historical compatible fixture.
        example["contract_version"] = (_support.REPO / "contracts" / "VERSION").read_text().strip()
        self.assertEqual(validate_document(doc), [])
        self.assertEqual(doc, example)

    def test_reject_and_validation(self):
        doc = commands.build_review_command("reject_rows", "b2026_07_alpha", [7, 6, 6], reason="synthetic reason")
        self.assertEqual(doc["payload"]["row_numbers"], [6, 7])
        self.assertEqual(doc["expected_versions"], [])
        self.assertEqual(validate_document(doc), [])
        for bad in [dict(command_type="reject_rows", batch_id="b1", row_numbers=[1]),            # no reason
                    dict(command_type="approve_rows", batch_id="b1", row_numbers=[]),            # empty
                    dict(command_type="approve_rows", batch_id="b 1", row_numbers=[1]),          # bad id
                    dict(command_type="approve_rows", batch_id="b1", row_numbers=[0]),
                    dict(command_type="commit_batch", batch_id="b1", row_numbers=[1])]:          # not a review cmd
            with self.assertRaises(commands.CommandError, msg=bad):
                commands.build_review_command(**bad)

    def test_precheck_against_review_queue(self):
        q = reports.read_report_csv(_support.REPORTS / "rpt_review_queue.csv", "rpt_review_queue")
        self.assertEqual(commands.precheck_review_rows("approve_rows", "b2026_07_alpha", [1, 4], q), [])
        problems = commands.precheck_review_rows("approve_rows", "b2026_07_alpha", [2, 3, 99], q)
        self.assertEqual(len(problems), 3)
        self.assertEqual(commands.precheck_review_rows("reject_rows", "b2026_07_alpha", [2, 3], q), [])


class Outbox(unittest.TestCase):
    def test_write_never_overwrites(self):
        with _support.temp_dir() as root:
            doc = commands.build_review_command("approve_rows", "b2026_07_alpha", [1, 4])
            path = commands.write_to_outbox(doc, root)
            self.assertEqual(path, root / "commands" / "outbox" / (doc["command_id"] + ".json"))
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), doc)
            with self.assertRaises(FileExistsError):
                commands.write_to_outbox(doc, root)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name])

    def test_refuses_data_root_inside_checkout(self):
        doc = commands.build_review_command("approve_rows", "b2026_07_alpha", [1])
        with self.assertRaises(commands.CommandError):
            commands.write_to_outbox(doc, _support.REPO / "tmp-data-root")
        self.assertFalse((_support.REPO / "tmp-data-root").exists())
        with _support.temp_dir() as d:
            synced = d / "OneDrive" / "PerFin"
            with self.assertRaises(commands.CommandError):
                commands.write_to_outbox(doc, synced)
            self.assertTrue(commands.write_to_outbox(doc, synced, acknowledged=True).is_file())

    def test_promote_vba_shaped_drafts(self):
        with _support.temp_dir() as root:
            drafts = root / "commands" / "drafts"
            drafts.mkdir(parents=True)
            for p in (_support.FIXTURES / "commands").glob("*.json"):
                shutil.copyfile(p, drafts / p.name)
            bad = commands.build_review_command("approve_rows", "b2026_07_alpha", [1])
            bad["payload"]["row_numbers"] = [1.5]
            (drafts / (bad["command_id"] + ".json")).write_text(json.dumps(bad), encoding="utf-8")
            (drafts / "not-a-uuid.json").write_text(json.dumps(
                commands.build_review_command("approve_rows", "b2026_07_alpha", [1])), encoding="utf-8")
            report = commands.promote_drafts(root)
            self.assertEqual(report["promoted"], ["6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5.json"])
            self.assertEqual(len(report["rejected"]), 2)
            out = _support.load_json(root / "commands" / "outbox" / report["promoted"][0])
            self.assertEqual(out["payload"]["reason"], "é synthetic \"quoted\" reason")
            self.assertEqual(list(drafts.iterdir()), [])
            rejected = sorted(p.name for p in (root / "commands" / "rejected").iterdir())
            self.assertEqual(len(rejected), 4)  # each draft plus its .errors.json

    def test_promote_rejects_non_object_drafts(self):
        """Codex P2: JSON null (and other non-objects) must never reach the outbox."""
        uid = "6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5"
        for body in ("null", "[]", "[1, 2]", "5", "-0.5", '"x"', "true"):
            with _support.temp_dir() as root:
                drafts = root / "commands" / "drafts"
                drafts.mkdir(parents=True)
                (drafts / (uid + ".json")).write_text(body, encoding="utf-8")
                report = commands.promote_drafts(root)
                self.assertEqual(report["promoted"], [], body)
                self.assertEqual([n for n, _ in report["rejected"]], [uid + ".json"], body)
                self.assertEqual(report["rejected"][0][1][0][0], "E_TYPE", body)
                self.assertFalse((root / "commands" / "outbox").exists() and
                                 any((root / "commands" / "outbox").iterdir()), body)
                rejected = root / "commands" / "rejected"
                self.assertEqual((rejected / (uid + ".json")).read_text(encoding="utf-8"), body)
                errs = json.loads((rejected / (uid + ".json.errors.json")).read_text(encoding="utf-8"))
                self.assertEqual(errs[0][0], "E_TYPE")
                self.assertEqual(list(drafts.iterdir()), [])
        for bad in (None, [], 5, "x"):
            with self.assertRaises(commands.CommandError):
                commands.validate(bad)
            with _support.temp_dir() as root, self.assertRaises(commands.CommandError):
                commands.write_to_outbox(bad, root)

    def test_vba_builder_emits_every_required_field(self):
        text = (_support.CORE / "vba" / "PerFinCommands.bas").read_text(encoding="utf-8")
        schema = _support.load_json(_support.REPO / "contracts" / "schemas" / "command.schema.json")
        for key in schema["required"] + ["batch_id", "row_numbers", "reason"]:
            self.assertIn('""%s""' % key, text, key)
        self.assertIn('ISSUED_BY As String = "excel_core:review_sheet"', text)

    def test_cli(self):
        import contextlib
        import io
        from perfin_excel_core.__main__ import main
        with _support.temp_dir() as root, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["command", "approve", "--data-root", str(root), "--batch-id", "b2026_07_alpha",
                                   "--rows", "1,4"]), 0)
            self.assertEqual(len(list((root / "commands" / "outbox").iterdir())), 1)
            self.assertEqual(main(["command", "promote", "--data-root", str(root)]), 0)
        self.assertIn("outbox", out.getvalue())


if __name__ == "__main__":
    unittest.main()
