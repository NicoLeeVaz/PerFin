"""Build deterministic source ZIP and local wheel from a clean revision.

No dependency download occurs. Install the declared build prerequisites first.
Only Git-tracked source is packaged; public runtime data is refused.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SUFFIXES = {".accdb", ".mdb", ".laccdb", ".ldb", ".xlsx", ".xlsm", ".pdf", ".zip", ".log", ".pem", ".key"}
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", "node_modules", "backups", "outbox", "logs"}


def check_source_path(path):
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or set(p.parts) & FORBIDDEN_PARTS:
        raise ValueError("unsafe source path: " + str(path))
    if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name.startswith(".env"):
        raise ValueError("runtime/private artifact cannot ship: " + str(path))


def source_zip(root, paths, destination):
    """Stable byte order, timestamps and modes, independent of checkout mtimes."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(paths):
            check_source_path(name)
            p = root / name
            if p.is_symlink() or not p.is_file():
                raise ValueError("source must be a regular file: " + name)
            info = zipfile.ZipInfo("PerFin/" + name.replace(os.sep, "/"), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, p.read_bytes(), compresslevel=9)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="new output directory outside checkout")
    ap.add_argument("--source-only", action="store_true")
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if out == ROOT or ROOT in out.parents:
        ap.error("release outputs must be outside the source checkout")
    if out.exists():
        ap.error("output directory already exists; use a fresh one")
    if git("status", "--porcelain", "--untracked-files=all"):
        ap.error("commit and review all source changes before packaging a release revision")
    subprocess.run([sys.executable, "-B", "config/privacy/perfin_privacy_checks.py", "scan-repo", "."], cwd=ROOT, check=True)
    revision = git("rev-parse", "HEAD")
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    names = [n for n in names if n]
    for name in names:
        check_source_path(name)
    out.mkdir(parents=True)
    source_zip(ROOT, names, out / ("PerFin-" + revision[:12] + "-source.zip"))
    if not args.source_only:
        env = dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", "HEAD"), PYTHONHASHSEED="0",
                   PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-index",
                        "--wheel-dir", str(out), str(ROOT)], env=env, cwd=ROOT, check=True)
    artifacts = {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                 for p in sorted(out.iterdir()) if p.is_file()}
    (out / "SHA256SUMS").write_text("".join(v["sha256"] + "  " + k + "\n" for k, v in artifacts.items()), encoding="ascii")
    (out / "release-manifest.json").write_text(json.dumps({"revision": revision, "artifacts": artifacts,
        "python": sys.version.split()[0], "build_tools": {name: version(name) for name in ("setuptools", "wheel")},
        "source_timestamp": "1980-01-01T00:00:00", "runtime_acceptance": "PENDING; attach separate Windows evidence"}, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
