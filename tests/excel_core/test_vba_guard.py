"""VBA data-root location guard (Codex P1): lists match 1c, and it runs before any write."""
import re
import unittest
from pathlib import PureWindowsPath

import _support

VBA = _support.CORE / "vba"
DEFAULTS = _support.load_json(_support.REPO / "config" / "privacy" / "defaults.json")["data_dir"]


def const(text, name):
    m = re.search(r"Public Const %s As String = (.*?)\n(?!\s+\")" % name, text + "\n", re.S)
    return "".join(re.findall(r'"([^"]*)"', m.group(1)))


def procedures(text):
    """{name: body} for every Sub/Function in a module."""
    out = {}
    for m in re.finditer(r"(?im)^(?:Public |Private )?(?:Sub|Function) (\w+)\(.*?^End (?:Sub|Function)", text, re.S | re.M):
        out[m.group(1)] = m.group(0)
    return out


CORE = (VBA / "PerFinCore.bas").read_text(encoding="utf-8")
GUARD = re.compile(r"PerFin_(?:DataRootProblem|CheckedDataRoot)\(")
WRITE = re.compile(r"(?im)^\s*(?:Open .* For (?:Output|Append|Binary)|Print #|MkDir |PerFin_EnsureFolder |PerFin_WriteNewAsciiFile )")


class Lists(unittest.TestCase):
    def test_vba_lists_equal_defaults_json(self):
        self.assertEqual(const(CORE, "PERFIN_SYNC_MARKERS").split("|"), DEFAULTS["sync_markers"])
        self.assertEqual(const(CORE, "PERFIN_SYNC_MARKER_PREFIXES").split("|"), DEFAULTS["sync_marker_prefixes"])
        self.assertEqual(const(CORE, "PERFIN_SYNC_ENV_VARS").split("|"), DEFAULTS["sync_env_vars"])
        self.assertTrue(DEFAULTS["refuse_inside_git_checkout"])
        self.assertEqual(const(CORE, "PERFIN_DATA_DIR_MARKER"), "perfin-data-dir.json")


class Order(unittest.TestCase):
    def test_draft_procedure_guards_before_writing(self):
        body = procedures((VBA / "PerFinCommands.bas").read_text(encoding="utf-8"))["BuildReviewDraft"]
        guard = GUARD.search(body)
        writes = [m.start() for m in WRITE.finditer(body)]
        self.assertTrue(guard and writes)
        self.assertLess(guard.start(), min(writes))
        # the guard result is acted on (Exit Sub) before the review table is even read
        self.assertLess(body.index("Exit Sub", guard.start()), body.index('PerFin_FindTable("rpt_review_queue")'))
        self.assertNotIn("PerFin_IsLocalPath(folder)", body)

    def test_every_writer_is_guarded(self):
        for path in sorted(VBA.glob("*.bas")):
            for name, body in procedures(path.read_text(encoding="utf-8")).items():
                writes = [m.start() for m in WRITE.finditer(body)]
                if not writes:
                    continue
                g = GUARD.search(body)
                self.assertTrue(g and g.start() < min(writes), "%s.%s writes before the guard" % (path.name, name))

    def test_helpers_enforce_root_containment(self):
        procs = procedures(CORE)
        for name in ("PerFin_EnsureFolder", "PerFin_WriteNewAsciiFile"):
            self.assertIn("PerFin_IsUnder(", procs[name], name)


# A line-by-line Python model of PerFin_DataRootProblem (labelled MODEL: VBA not executed here).
def model_problem(root, exists, env):
    if root.startswith(("\\\\", "//")):
        return "network (UNC) path"
    if not re.match(r"^[A-Za-z]:\\", root):
        return "not an absolute local drive path"
    parts = root.split("\\")
    for p in parts[1:]:
        if p.casefold() in {m.casefold() for m in DEFAULTS["sync_markers"]} or any(
                p.casefold().startswith(x.casefold()) for x in DEFAULTS["sync_marker_prefixes"]):
            return "sync"
    for var in DEFAULTS["sync_env_vars"]:
        v = env.get(var, "").rstrip("\\")
        if v and (root.casefold() == v.casefold() or root.casefold().startswith(v.casefold() + "\\")):
            return "env"
    cur = parts[0]
    if exists(cur + "\\.git"):
        return "git"
    for p in parts[1:]:
        if p:
            cur += "\\" + p
            if exists(cur + "\\.git"):
                return "git"
    if not exists(root + "\\perfin-data-dir.json"):
        return "marker"
    return ""


class Model(unittest.TestCase):
    def test_model_refusals(self):
        files = {r"C:\src\PerFin\.git", r"C:\Users\u\AppData\Local\PerFin\perfin-data-dir.json",
                 r"C:\src\PerFin\data\perfin-data-dir.json", r"D:\OneDrive\PerFin\perfin-data-dir.json"}
        exists = lambda p: p in files  # noqa: E731
        env = {"OneDriveCommercial": r"C:\Users\u\Work Files"}
        cases = {
            r"C:\Users\u\AppData\Local\PerFin": "",
            r"C:\src\PerFin\data": "git",
            r"D:\OneDrive\PerFin": "sync",
            r"C:\Users\u\OneDrive - Contoso\PerFin": "sync",
            r"C:\Users\u\Work Files\PerFin": "env",
            "\\\\server\\share\\PerFin": "network (UNC) path",
            r"C:\Users\u\AppData\Local\Other": "marker",
        }
        for root, want in cases.items():
            self.assertEqual(model_problem(root, exists, env), want, root)
        # the Python 1c check (run again at promote time) also blocks a sync root
        from perfin_privacy_checks import evaluate_data_dir
        self.assertEqual(evaluate_data_dir(PureWindowsPath(r"D:\OneDrive\PerFin"), env={},
                                           check_filesystem=False)["decision"], "warn")


if __name__ == "__main__":
    unittest.main()
