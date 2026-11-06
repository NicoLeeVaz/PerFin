"""Installed-wheel resources work away from checkout; forbidden decoys never ship."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from scenario import ROOT


class Wheel(unittest.TestCase):
    def test_wheel_is_self_contained_and_excludes_private_decoys(self):
        # Test packaging against an isolated source copy, so concurrent static
        # safety checks never observe deliberately forbidden fixtures in ROOT.
        with tempfile.TemporaryDirectory(prefix='perfin-wheel-') as d:
            source=Path(d)/'source'
            shutil.copytree(ROOT,source,ignore=shutil.ignore_patterns(
                '.git','build','dist','*.egg-info','__pycache__','*.pyc','*.accdb','*.sqlite','*.sqlite3','*.db'))
            decoy=source/'access/synthetic-private-decoy.accdb'
            stale=source/'build/lib/perfin_resources/data/private-decoy.accdb'
            decoy.write_text('SYNTHETIC DO NOT PACKAGE')
            stale.parent.mkdir(parents=True,exist_ok=True);stale.write_text('SYNTHETIC STALE BUILD')
            built=subprocess.run([sys.executable,'-m','pip','wheel','--no-deps','--no-index','--no-build-isolation',str(source),
                        '--wheel-dir',d],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            wheel=next(Path(d).glob('*.whl'));target=Path(d)/'installed'
            with zipfile.ZipFile(wheel) as z:
                names=z.namelist()
                self.assertFalse(any('private-decoy' in n or n.endswith('.accdb') for n in names))
                z.extractall(target)
            script='''import sys,json
sys.path.insert(0,sys.argv[1])
from perfin_resources import root
from perfin_contracts.semantic import validate_document
from perfin_store import _paths,ddl
from perfin_import import builtin_profiles
from perfin_excel_core import spec,registry
assert root().is_dir()
assert ddl.registry()
assert builtin_profiles()
assert spec.columns("rpt_accounts")
assert _paths.privacy().load_defaults()["nopii"]["raw_fallback_allowed"] is False
from perfin_app.__main__ import parser
assert parser().parse_args(["status"]).action == "status"
import contextlib,io,tempfile
from pathlib import Path
from perfin_app.__main__ import main
with tempfile.TemporaryDirectory(prefix="perfin-installed-sqlite-") as private:
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["--data-root",private,"init","--demo"]) == 0
        assert main(["--data-root",private,"status"]) == 0
    assert (Path(private)/"db/perfin.sqlite").is_file()
    assert not (Path(private)/"db/perfin.accdb").exists()
print("installed resource smoke passed")
'''
            smoke=subprocess.run([sys.executable,'-I','-c',script,str(target)],cwd=d,capture_output=True,text=True)
            self.assertEqual(smoke.returncode,0,smoke.stderr)
