import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "excel/payoff"), str(ROOT / "excel/core"), str(ROOT / "contracts/python")]
from openpyxl import load_workbook
from perfin_excel_payoff import build, read_scenario, recompute, save_command, install
from perfin_excel_payoff.workbook import _number
from perfin_contracts.semantic import validate_document
from perfin_excel_core import registry
from perfin_payoff import simulate


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="perfin-payoff-test-")
        self.root = Path(self.temp.name)
        self.path = self.root / "PerFin-Payoff.xlsx"
        self.doc = json.loads((ROOT / "fixtures/payoff/scenario.synthetic.json").read_text())

    def tearDown(self):
        self.temp.cleanup()

    def test_build_and_roundtrip_match_engine(self):
        result = build(self.doc, self.path)
        reread = read_scenario(self.path)
        # Optional false lock_target is materialized by the editable workbook.
        self.doc["scenario"]["strategies"][0]["lock_target"] = False
        self.assertEqual(reread, self.doc)
        wb = load_workbook(self.path)
        self.assertEqual(wb["Plan"]["C5"].value, result["results"][0]["total_interest_minor"] / 100)
        self.assertEqual(wb["Plan"]["F5"].value, 0)
        self.assertIn("INPUTS CHANGED", wb["Plan"]["L3"].value)
        self.assertEqual(wb["_Baseline"].sheet_state, "veryHidden")
        self.assertEqual(len(wb["Plan"]._charts), 1)
        self.assertEqual(wb._external_links, [])
        wb.close()

    def test_budget_apr_strategy_edit_recomputes(self):
        initial = build(self.doc, self.path)
        wb = load_workbook(self.path)
        wb["Inputs"]["B6"] = 1000
        wb["Inputs"]["B8"] = "snowball"
        wb["Cards"]["D5"] = .18
        wb.save(self.path)
        wb.close()
        edited = read_scenario(self.path)
        self.assertEqual(edited["scenario"]["cash_plan"]["monthly_minor"], 100000)
        self.assertEqual(edited["scenario"]["cards"][0]["buckets"][0]["apr"], "0.18")
        after = recompute(self.path)
        self.assertEqual(after, simulate(edited))
        self.assertEqual(after["results"][0]["strategy"]["kind"], "snowball")
        self.assertLess(after["results"][0]["debt_free_month"], initial["results"][0]["debt_free_month"])

    def test_unknown_or_formula_inputs_fail_without_overwrite(self):
        build(self.doc, self.path)
        wb = load_workbook(self.path)
        wb["Inputs"]["B6"] = "=100+200"
        wb.save(self.path)
        wb.close()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError): recompute(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_subcent_coercion(self):
        with self.assertRaises(ValueError): _number(1.001, minor=True)
        with self.assertRaises(ValueError): _number(True, integer=True)
        with self.assertRaises(ValueError): _number(float("nan"))
        self.assertEqual(_number(1.01, minor=True), 101)

    def test_horizon_and_unsupported_remain_visible(self):
        self.doc["scenario"]["horizon_months"] = 1
        self.doc["scenario"]["cash_plan"]["lump_sums"] = []
        build(self.doc, self.path)
        wb = load_workbook(self.path)
        self.assertEqual(wb["Plan"]["B5"].value, "horizon_reached")
        self.assertGreater(wb["Plan"]["F5"].value, 0)
        self.assertIsNone(wb["Plan"]["G5"].value)
        self.assertIsNone(wb["Plan"]["H5"].value)
        wb.close()

    def test_cash_event_edit_and_duplicate_override(self):
        build(self.doc, self.path)
        wb = load_workbook(self.path)
        events = wb["Cash events"]
        events.append(["override", 1, 750, None])
        wb.save(self.path); wb.close()
        doc = read_scenario(self.path)
        self.assertEqual(doc["scenario"]["cash_plan"]["overrides"], [{"month": 1, "amount_minor": 75000}])
        wb = load_workbook(self.path)
        wb["Cash events"].append(["override", 1, 750, None])
        wb.save(self.path); wb.close()
        with self.assertRaises(ValueError): read_scenario(self.path)

    def test_registry_and_save_command(self):
        folder = self.root / "modules/excel_payoff"
        folder.mkdir(parents=True)
        path = folder / "PerFin-Payoff.xlsx"
        build(self.doc, path)
        (folder / "module_manifest.json").write_bytes((ROOT / "excel/payoff/module_manifest.json").read_bytes())
        entries = registry.scan(self.root / "modules")
        self.assertEqual(entries[0]["status"], "OK")
        self.assertTrue(entries[0]["launchable"])
        command = save_command(read_scenario(path))
        self.assertEqual(validate_document(command), [])
        self.assertEqual(command["command_type"], "save_payoff_scenario")
        self.assertEqual(command["payload"]["cards"], self.doc["scenario"]["cards"])

    def test_refuse_repo_sync_and_escape(self):
        with self.assertRaises(Exception): build(self.doc, ROOT / "private.xlsx")
        with self.assertRaises(Exception): build(self.doc, self.root / "OneDrive/private.xlsx")
        with self.assertRaises(Exception): build(self.doc, self.path, data_root=self.root / "different")
        self.assertFalse((ROOT / "private.xlsx").exists())
        self.assertFalse((self.root / "OneDrive").exists())

    def test_multiple_hybrid_comparisons_survive_roundtrip(self):
        self.doc["scenario"]["strategies"] = [{"kind": "near_apr_hybrid", "gap_pp": str(g), "prefer": "largest"} for g in (0, .5, 1, 2)]
        build(self.doc, self.path)
        result = read_scenario(self.path)
        hybrids = [x for x in result["scenario"]["strategies"] if x["kind"] == "near_apr_hybrid"]
        self.assertEqual([x["gap_pp"] for x in hybrids], ["0", "0.5", "1", "2"])
        self.assertEqual(len(recompute(self.path)["results"]), 5)

    def test_install_registers_bundled_manifest(self):
        install(self.doc, self.root)
        entries = registry.scan(self.root / "workbooks")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["module_id"], "excel_payoff")
        self.assertTrue(entries[0]["launchable"])
        self.assertTrue((self.root / "workbooks/excel_payoff/PerFin-Payoff.xlsx").exists())

    def test_build_refuses_unrequested_overwrite(self):
        build(self.doc, self.path)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): build(self.doc, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_multiple_buckets_are_preserved_and_refused(self):
        card = self.doc["scenario"]["cards"][0]
        second = copy.deepcopy(card["buckets"][0]); second["bucket_id"] = "cash_advance"
        card["buckets"].append(second)
        build(self.doc, self.path)
        reread = read_scenario(self.path)
        self.assertEqual(len(reread["scenario"]["cards"][0]["buckets"]), 2)
        self.assertEqual(simulate(reread)["results"][0]["run_status"], "unsupported_terms")


if __name__ == "__main__": unittest.main()
