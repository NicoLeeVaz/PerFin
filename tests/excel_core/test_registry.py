"""Module registry and launcher with mock module workbooks."""
import json
import shutil
import unittest

import _support
from openpyxl import Workbook
from perfin_excel_core import registry, reports, spec, workbook


def mock_modules(root):
    """Copy the fixture manifests and add tiny generated mock workbooks."""
    root.mkdir(parents=True, exist_ok=True)
    for mf in sorted(_support.MODULES.glob("*/module_manifest.json")):
        dst = root / mf.parent.name
        dst.mkdir()
        shutil.copyfile(mf, dst / mf.name)
        wb = Workbook()
        wb.active["A1"] = "mock module " + mf.parent.name
        wb.save(dst / json.loads(mf.read_text(encoding="utf-8"))["workbook_file"])
    return root


def add(root, name, doc, workbook_file=None):
    d = root / name
    d.mkdir()
    (d / "module_manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    if workbook_file:
        Workbook().save(d / workbook_file)


class Registry(unittest.TestCase):
    def setUp(self):
        self.ctx = _support.temp_dir()
        self.d = self.ctx.__enter__()
        self.root = mock_modules(self.d / "workbooks")
        self.base = _support.load_json(_support.MODULES / "excel_payoff" / "module_manifest.json")

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def test_lists_valid_modules_sorted(self):
        entries = registry.scan(self.root)
        self.assertEqual([e["module_id"] for e in entries], ["excel_payoff", "excel_statements"])
        self.assertTrue(all(e["status"] == "OK" and e["launchable"] for e in entries))
        self.assertEqual(entries[0]["workbook_file"], "PerFin-Payoff.xlsm")

    def test_rejects_bad_manifests(self):
        writes = dict(self.base, module_id="bad_writer", writes_ledger=True)
        add(self.root, "bad_writer", writes, "PerFin-Payoff.xlsm")
        core = dict(self.base, module_id="hijack", workbook_file="PerFin-Core.xlsm")
        add(self.root, "hijack", core, "PerFin-Core.xlsm")
        add(self.root, "nofile", dict(self.base, module_id="nofile", workbook_file="Missing.xlsx"))
        add(self.root, "dupe", dict(self.base), "PerFin-Payoff.xlsm")
        add(self.root, "future", dict(self.base, module_id="future", contract_version="1.1.0"), "PerFin-Payoff.xlsm")
        (self.root / "broken").mkdir()
        (self.root / "broken" / "module_manifest.json").write_text("{not json", encoding="utf-8")
        by = {}
        for e in registry.scan(self.root):
            by.setdefault(e["module_dir"], e)
        self.assertIn("E_MODULE_WRITES_LEDGER", by["bad_writer"]["message"])
        self.assertIn("core workbook", by["hijack"]["message"])
        self.assertEqual(by["nofile"]["status"], "MISSING_FILE")
        self.assertIn("duplicate module_id", by["dupe"]["message"])
        self.assertIn("duplicate module_id", by["excel_payoff"]["message"])
        self.assertIn("E_VERSION_UNSUPPORTED", by["future"]["message"])
        self.assertEqual(by["broken"]["status"], "INVALID")
        self.assertEqual([e["module_dir"] for e in registry.scan(self.root) if e["launchable"]], ["excel_statements"])

    def test_launch_opens_the_modules_own_workbook(self):
        opened = []
        path = registry.launch(self.root, "excel_statements", opener=opened.append)
        self.assertEqual(opened, [path])
        self.assertEqual(path, (self.root / "excel_statements" / "PerFin-Statements.xlsm").resolve())
        self.assertNotEqual(path.name.lower(), "perfin-core.xlsm")
        with self.assertRaises(registry.LaunchError):
            registry.launch(self.root, "unknown", opener=opened.append)
        add(self.root, "nofile", dict(self.base, module_id="nofile", workbook_file="Missing.xlsx"))
        with self.assertRaises(registry.LaunchError):
            registry.launch(self.root, "nofile", opener=opened.append)
        self.assertEqual(len(opened), 1)

    def test_registry_csv_feeds_the_core_workbook(self):
        out = self.d / "reports" / spec.MODULES_CSV
        out.parent.mkdir()
        registry.export_csv(self.root, out)
        rows = reports.read_report_csv(out, spec.MODULES_TABLE)
        self.assertEqual([r["module_id"] for r in rows], ["excel_payoff", "excel_statements"])
        self.assertTrue(all(r["launchable"] is True for r in rows))
        from openpyxl import load_workbook
        from formula_eval import Evaluator
        import datetime as dt
        workbook.build(self.d / "core.xlsx", modules_dir=self.root)
        ev = Evaluator(load_workbook(self.d / "core.xlsx"), dt.date(2026, 7, 2))
        self.assertEqual(ev.name_ref("PerFin_ModuleCount"), 2)
        self.assertEqual(ev.name_ref("PerFin_ModulesLaunchable"), 2)
        self.assertEqual(ev.name_ref("PerFin_ModulesInvalid"), 0)

    def test_core_build_never_touches_module_workbooks(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        workbook.build(self.d / "core.xlsx", modules_dir=self.root)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_vba_launcher_guards(self):
        text = (_support.CORE / "vba" / "PerFinLauncher.bas").read_text(encoding="utf-8")
        for guard in ('"OK"', "launchable", "PerFin_IsPlainName", "perfin-core.xls?", "UpdateLinks:=0",
                      "PerFin_IsLocalPath"):
            self.assertIn(guard, text)


if __name__ == "__main__":
    unittest.main()
