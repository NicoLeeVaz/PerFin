"""Generated model drift and independent reference-schema checks."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_model", ROOT / "scripts/database/build_model.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class DatabaseModel(unittest.TestCase):
    def test_generated_documents_are_current(self):
        for name, content in model.outputs().items():
            with self.subTest(name=name):
                self.assertEqual((ROOT / "docs/database" / name).read_text(), content)

    def test_inventory_matches_frozen_reference_tables_keys_and_columns(self):
        saved = json.loads((ROOT / "docs/database/schema-inventory.json").read_text())
        reference = {t.name: t for t in [model.ddl.parse_create_table(s) for s in
                     model.ddl.split_statements((ROOT / "contracts/access/perfin_v1_reference.sql").read_text())]}
        self.assertEqual({t["name"] for t in saved["tables"]}, set(reference))
        for table in saved["tables"]:
            with self.subTest(table=table["name"]):
                expected = reference[table["name"]]
                self.assertEqual([(c["name"], c["type"], c["length"], c["not_null"]) for c in table["columns"]],
                                 [(c.name, c.type, c.length, c.not_null) for c in expected.columns.values()])
                self.assertEqual(table["primary_key"], list(expected.primary_key))
                self.assertEqual(table["unique_keys"], [list(k) for k in expected.uniques])
                self.assertEqual([(f["column"], f["table"], f["target_column"]) for f in table["foreign_keys"]],
                                 expected.foreign_keys)

    def test_declared_and_logical_links_are_distinct(self):
        data = model.inventory()
        tables = {t["name"]: t for t in data["tables"]}
        self.assertEqual({f["column"] for f in tables["audit_log"]["foreign_keys"]}, {"command_id"})
        self.assertNotIn("source_row_number", {f["column"] for f in tables["ledger_txn"]["foreign_keys"]})
        self.assertTrue(any(r["source_table"] == "ledger_txn" and r["target_table"] == "staging_row"
                            for r in data["logical_relationships"]))
        for table in tables.values():
            for fk in table["foreign_keys"]:
                self.assertIn(fk["target_column"], [c["name"] for c in tables[fk["table"]]["columns"]])

    def test_explorer_embeds_inventory_and_needs_no_network(self):
        page = (ROOT / "docs/database/model.html").read_text()
        payload = re.search(r'<script id="inventory" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(payload), model.inventory())
        self.assertNotRegex(page, r'<(?:script|link)[^>]+(?:src|href)=["\']https?://')
        self.assertNotRegex(page, r'\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(')


if __name__ == "__main__":
    unittest.main()
