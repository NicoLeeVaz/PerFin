"""The offline-compatibility checker passes the generated workbook and catches every rule."""
import base64
import io
import unittest
import zipfile

import _support
from perfin_excel_core import offline_check as oc
from perfin_excel_core import powerquery, workbook


def rules(findings, severity="ERROR"):
    return {f.rule for f in findings if f.severity == severity}


def rewrite(src, dst, add=None, edit=None):
    """Copy an .xlsx package, adding parts and editing existing parts (synthetic tampering)."""
    add, edit = add or {}, edit or {}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in edit:
                data = edit[item.filename](data)
            zout.writestr(item, data)
        for name, data in add.items():
            zout.writestr(name, data)
    return dst


def mashup(m_text):
    pkg = io.BytesIO()
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("Formulas/Section1.m", "section Section1;\r\nshared Q = " + m_text + ";")
    raw = pkg.getvalue()
    blob = (0).to_bytes(4, "little") + len(raw).to_bytes(4, "little") + raw + (0).to_bytes(4, "little")
    xml = '<?xml version="1.0" encoding="utf-16"?><DataMashup xmlns="http://schemas.microsoft.com/DataMashup">%s</DataMashup>'
    return (xml % base64.b64encode(blob).decode()).encode("utf-16")


class Workbooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _support.temp_dir()
        cls.d = cls.ctx.__enter__()
        cls.tpl = workbook.build(cls.d / "PerFin-Core.xlsx")
        cls.snap = workbook.build(cls.d / "snap.xlsx", report_dir=_support.copy_reports(cls.d / "r"),
                                  checked_at=_support.CHECKED_AT)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_generated_workbooks_pass(self):
        for p in (self.tpl, self.snap):
            self.assertEqual([f for f in oc.check_workbook(p) if f.severity != "INFO"], [], p)
        with zipfile.ZipFile(self.snap) as z:
            names = z.namelist()
        self.assertFalse([n for n in names if "externalLink" in n or "connections" in n or "vbaProject" in n])

    def sheet_edit(self, needle, replacement):
        def f(data):
            text = data.decode("utf-8")
            self.assertIn(needle, text)
            return text.replace(needle, replacement, 1).encode("utf-8")
        return f

    def tampered(self, name, **kw):
        return oc.check_workbook(rewrite(self.snap, self.d / name, **kw))

    def test_external_link_part(self):
        f = self.tampered("ext.xlsx", add={"xl/externalLinks/externalLink1.xml": b"<externalLink/>"})
        self.assertIn("external_link", rules(f))

    def test_connections(self):
        conn = ('<connections xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<connection id="1" name="web" type="4"><webPr url="https://example.invalid/x"/></connection>'
                '<connection id="2" name="pq" type="5"><dbPr connection="Provider=Microsoft.Mashup.OleDb.1;'
                'Data Source=$Workbook$;Location=rpt_accounts"/></connection>'
                '<connection id="3" name="acc" type="5"><dbPr connection="Provider=Microsoft.ACE.OLEDB.12.0;'
                'Data Source=C:\\PerFinData\\db\\PerFin.accdb"/></connection>'
                '<connection id="4" name="sql" type="1"><dbPr connection="DRIVER=SQL Server;SERVER=far"/></connection>'
                '<connection id="5" name="unc" type="5"><dbPr connection="Provider=Microsoft.ACE.OLEDB.12.0;'
                'Data Source=\\\\server\\share\\x.accdb"/></connection>'
                '<connection id="6" name="txt" type="6"><textPr sourceFile="C:\\PerFinData\\reports\\a.csv"/></connection>'
                '</connections>').encode()
        f = self.tampered("conn.xlsx", add={"xl/connections.xml": conn})
        where = {x.where for x in f if x.severity == "ERROR"}
        self.assertEqual(where, {"connection web", "connection sql", "connection unc"})
        self.assertIn("web_query", rules(f))

    def test_formulas(self):
        bad = {
            "network_formula": 'WEBSERVICE("https://example.invalid")',
            "remote_hyperlink_formula": 'HYPERLINK("https://example.invalid","x")',
            "dde_formula": "cmd|'/c calc'!A0",
            "volatile_formula": 'INDIRECT("A1")',
            "external_reference": "[1]Sheet1!A1",
            "code_formula": 'CALL("kernel32","x","J")',
        }
        for rule, formula in bad.items():
            f = self.tampered(rule + ".xlsx", edit={"xl/worksheets/sheet3.xml": self.sheet_edit(
                '<f>SUMIFS(rpt_accounts[display_balance_minor],rpt_accounts[kind],"asset")/100</f>',
                "<f>%s</f>" % formula.replace("&", "&amp;"))})
            self.assertIn(rule, rules(f), formula)
        self.assertEqual(oc._formula_findings("_xlfn.FILTERXML(A1,\"//x\")", "x")[0].rule, "network_formula")
        self.assertEqual(oc._formula_findings('IF(TODAY()-INT(B6)>7,"a","b")', "x"), [])
        self.assertEqual(oc._formula_findings('SUMIFS(t[a],t[b],"WEBSERVICE(")', "x"), [])  # inside a string

    def test_remote_hyperlink_relationship(self):
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'hyperlink" Target="https://example.invalid/" TargetMode="External"/></Relationships>').encode()
        f = self.tampered("link.xlsx", add={"xl/worksheets/_rels/sheet1.xml.rels": rels})
        self.assertIn("remote_hyperlink", rules(f))

    def test_unescaped_formula_text(self):
        f = self.tampered("text.xlsx", edit={"xl/styles.xml": lambda b: b.replace(b' quotePrefix="1"', b"")})
        self.assertIn("unescaped_text", rules(f))

    def test_embedded_power_query(self):
        good = self.tampered("pq_ok.xlsx", add={"customXml/item1.xml": mashup('File.Contents("C:\\\\x.csv")')})
        self.assertEqual(rules(good), set())
        bad = self.tampered("pq_bad.xlsx", add={"customXml/item1.xml": mashup('Web.Contents("https://example.invalid")')})
        self.assertIn("m_non_local_source", rules(bad))

    def test_parts(self):
        f = self.tampered("parts.xlsx", add={"xl/vbaProject.bin": b"x", "xl/webextensions/webextension1.xml": b"<x/>",
                                              "xl/embeddings/oleObject1.bin": b"x"})
        self.assertTrue({"vba_in_xlsx", "web_addin", "embedded_object"} <= rules(f))


class TextSources(unittest.TestCase):
    def test_committed_vba_and_m_pass(self):
        self.assertEqual(oc.check_vba_dir(_support.CORE / "vba"), [])
        self.assertEqual(oc.check_powerquery_dir(_support.CORE / "powerquery"), [])
        self.assertEqual(len(list((_support.CORE / "vba").glob("*.bas"))), 5)

    def test_vba_rules(self):
        cases = {
            "vba_network": 'Set x = New MSXML2.XMLHTTP60',
            "vba_process": 'Shell "ping example.invalid"',
            "vba_url": 'Workbooks.Open "https://example.invalid/a.xlsx"',
            "vba_hyperlink": 'ThisWorkbook.FollowHyperlink "x"',
            "vba_object": 'Set o = CreateObject("WinHttp.WinHttpRequest.5.1")',
            "vba_mail": "Set m = Outlook.Application",
            "vba_declare": 'Private Declare PtrSafe Function InternetOpenA Lib "wininet.dll" () As LongPtr',
            "vba_dynamic": 'Application.Run "Other.xlsm!Macro"',
        }
        for rule, line in cases.items():
            self.assertIn(rule, rules(oc.check_vba_text("Sub X()\n" + line + "\nEnd Sub\n", "t.bas")), line)
        clean = "' Shell and XMLHTTP mentioned in a comment only\nRem WinHttp\nMsgBox \"core shell ready\"\n"
        self.assertEqual(oc.check_vba_text(clean, "t.bas"), [])
        ok = 'Private Declare PtrSafe Sub GetSystemTime Lib "kernel32" (s As Any)\n'
        self.assertEqual(oc.check_vba_text(ok, "t.bas"), [])

    def test_m_rules(self):
        for text, rule in [('Web.Contents("x")', "m_non_local_source"), ('OData.Feed("x")', "m_non_local_source"),
                           ('SharePoint.Files("x")', "m_non_local_source"), ('Odbc.Query("dsn","q")', "m_non_local_source"),
                           ('Foo.Contents("x")', "m_unknown_source"), ('File.Contents("\\\\srv\\s\\a.csv")', "m_remote_literal")]:
            self.assertIn(rule, rules(oc.check_m_text(text, "q")), text)
        self.assertEqual(oc.check_m_text('// Web.Contents in a comment\nFile.Contents("C:\\a")', "q"), [])

    def test_cli_check(self):
        import contextlib
        from perfin_excel_core.__main__ import main
        with _support.temp_dir() as d, contextlib.redirect_stdout(io.StringIO()) as out:
            p = workbook.build(d / "PerFin-Core.xlsx")
            self.assertEqual(main(["check", str(p), "--vba", str(_support.CORE / "vba"),
                                   "--powerquery", str(_support.CORE / "powerquery")]), 0)
            bad = rewrite(p, d / "bad.xlsx", add={"xl/externalLinks/externalLink1.xml": b"<x/>"})
            self.assertEqual(main(["check", str(bad)]), 1)
        self.assertIn("external_link", out.getvalue())


class PowerQuery(unittest.TestCase):
    def test_committed_files_match_generator(self):
        expected = powerquery.queries()
        root = _support.CORE / "powerquery"
        committed = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())
        self.assertEqual(committed, sorted(expected))
        for rel, text in expected.items():
            raw = (root / rel).read_bytes()
            self.assertEqual(raw, text.replace("\n", "\r\n").encode("ascii"), rel)

    def test_queries_follow_the_contract(self):
        from perfin_excel_core import spec
        root = _support.CORE / "powerquery"
        for table in spec.CORE_SOURCES:
            text = (root / (table + ".pq")).read_text(encoding="ascii")
            cols = [ln.strip().split('"')[1] for ln in text.splitlines() if ln.strip().startswith('{"')]
            self.assertEqual(cols, spec.column_names(table), table)
        manifest = [ln.split("|") for ln in (root / "queries.txt").read_text(encoding="ascii").splitlines()
                    if ln and not ln.startswith("#")]
        loaded = {n for n, how in manifest if how == "table"}
        self.assertEqual(loaded, set(workbook.TABLE_PLACES))
        self.assertEqual(manifest[-1][0], "perfin_refresh_status")  # status is refreshed last
        for n, _ in manifest:
            self.assertTrue((root / (n + ".pq")).is_file(), n)
        vba = (_support.CORE / "vba" / "PerFinCore.bas").read_text(encoding="utf-8")
        order = vba.split('PERFIN_REFRESH_ORDER As String = _')[1].split("Private Type")[0]
        self.assertEqual([x for x in "".join(p.split('"')[1] for p in order.split("&")).split(",")],
                         [n for n, how in manifest if how == "table"])
        for forbidden in ("Web.", "OData", "SharePoint", "Python", "Excel.CurrentWorkbook"):
            for p in root.rglob("*.pq"):
                code = oc._strip_m_comments(p.read_text(encoding="ascii"))
                self.assertNotIn(forbidden, code, p.name)


if __name__ == "__main__":
    unittest.main()
