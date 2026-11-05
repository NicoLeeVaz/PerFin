"""Windows environment check for the Access backend. Makes no network calls.

    python -m perfin_store envcheck [--json]

Reports Windows version, Python version and bitness, Office version/bitness/channel (Click-to-Run
registry), whether Access is installed as the full product or the Runtime (heuristic), the ODBC
drivers registered for this process's bitness and for the other bitness, the ACE OLE DB
providers, pyodbc availability, and a verdict for the primary adapter (pyodbc + ACE ODBC).

Registry locations are from common Office deployments and are [Unverified] on the user's
machine; the report says "unknown" rather than guessing. On a non-Windows host it reports
"unsupported platform" and exits with status 2.
"""
from __future__ import annotations

import json
import platform
import struct
import sys
from typing import Any, Dict, List, Optional

ACE_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"
EXIT_OK, EXIT_PROBLEM, EXIT_UNSUPPORTED = 0, 1, 2


def python_info() -> Dict[str, Any]:
    return {"version": platform.python_version(), "implementation": platform.python_implementation(),
            "bits": struct.calcsize("P") * 8, "executable_is_64bit": sys.maxsize > 2 ** 32}


def _reg_values(root, path: str, view: int = 0) -> Optional[Dict[str, Any]]:
    import winreg
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
            out, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    return out
                out[name] = value
                i += 1
    except OSError:
        return None


def _reg_exists(root, path: str, view: int = 0) -> bool:
    import winreg
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view):
            return True
    except OSError:
        return False


def odbc_drivers(view_name: str) -> Optional[List[str]]:
    import winreg
    view = {"64": winreg.KEY_WOW64_64KEY, "32": winreg.KEY_WOW64_32KEY}[view_name]
    values = _reg_values(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers", view)
    return None if values is None else sorted(values)


def office_info() -> Dict[str, Any]:
    import winreg
    info: Dict[str, Any] = {"click_to_run": None, "msi_bitness": None, "products": [], "access": "not found"}
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        c2r = _reg_values(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration", view)
        if c2r:
            info["click_to_run"] = {"platform": c2r.get("Platform"), "version": c2r.get("VersionToReport"),
                                    "channel": c2r.get("CDNBaseUrl") and "configured" or None}
            info["products"] = sorted(str(c2r.get("ProductReleaseIds", "")).split(",")) if c2r.get("ProductReleaseIds") else []
            break
    for ver in ("16.0", "15.0", "14.0"):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            v = _reg_values(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\%s\Outlook" % ver, view)
            if v and v.get("Bitness"):
                info["msi_bitness"] = {"office_version": ver, "bitness": v.get("Bitness")}
                break
        if info["msi_bitness"]:
            break
    has_exe = _reg_exists(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MSACCESS.EXE")
    products = [p.strip() for p in info["products"]]
    runtime = any("AccessRuntime" in p for p in products)
    full = any(p.startswith(("Access", "O365", "ProPlus", "Professional", "Microsoft365")) and "Runtime" not in p
               for p in products)
    if full and has_exe:
        info["access"] = "full (Click-to-Run product list includes Access-capable suite) [Unverified heuristic]"
    elif runtime:
        info["access"] = "runtime (AccessRuntime product id) [Unverified heuristic]"
    elif has_exe:
        info["access"] = "installed; full versus Runtime not determinable from the registry [Unverified]"
    providers = [p for p in ("Microsoft.ACE.OLEDB.12.0", "Microsoft.ACE.OLEDB.16.0")
                 if _reg_exists(winreg.HKEY_CLASSES_ROOT, p)]
    info["ace_oledb_providers"] = providers
    return info


def pyodbc_info() -> Dict[str, Any]:
    try:
        import pyodbc
    except ImportError:
        return {"installed": False, "drivers": None}
    return {"installed": True, "version": getattr(pyodbc, "version", None), "drivers": sorted(pyodbc.drivers())}


def collect() -> Dict[str, Any]:
    report: Dict[str, Any] = {"tool": "perfin_store.envcheck", "network_calls": "none", "python": python_info()}
    if sys.platform != "win32":
        report.update({"status": "unsupported platform", "platform": sys.platform,
                       "detail": "The Access backend needs Windows with the Microsoft ACE ODBC driver. "
                                 "Linux/macOS can run only the unit tests against the test-only fake adapter."})
        return report
    report["windows"] = {"release": platform.release(), "version": platform.version(),
                         "edition": getattr(platform, "win32_edition", lambda: None)(), "machine": platform.machine()}
    bits = report["python"]["bits"]
    same, other = ("64", "32") if bits == 64 else ("32", "64")
    drivers_same, drivers_other = odbc_drivers(same), odbc_drivers(other)
    report["odbc_drivers"] = {"python_bitness_view_%s" % same: drivers_same, "other_view_%s" % other: drivers_other}
    report["office"] = office_info()
    report["pyodbc"] = pyodbc_info()
    ace_here = ACE_DRIVER in (report["pyodbc"]["drivers"] or drivers_same or [])
    ace_other = ACE_DRIVER in (drivers_other or [])
    problems = []
    if not ace_here:
        problems.append("ACE ODBC driver '%s' is not registered for %d-bit Python%s" % (
            ACE_DRIVER, bits, " (it is registered for %s-bit: install %s-bit Python, matching Office)" % (other, other)
            if ace_other else "; install the Microsoft Access Database Engine matching your Office bitness"))
    if not report["pyodbc"]["installed"]:
        problems.append("pyodbc is not installed (pinned: pyodbc==5.3.0; see docs/access/README.md)")
    office_bits = ((report["office"].get("click_to_run") or {}).get("platform")
                   or (report["office"].get("msi_bitness") or {}).get("bitness"))
    if office_bits and str(office_bits).lower() in ("x86", "x64"):
        ob = "64" if str(office_bits).lower() == "x64" else "32"
        if ob != str(bits):
            problems.append("Office is %s-bit but Python is %d-bit; ACE bitness follows Office" % (ob, bits))
    report["primary_adapter"] = {"name": "pyodbc + Microsoft ACE ODBC driver", "driver": ACE_DRIVER,
                                 "ready": not problems}
    report["problems"] = problems
    report["status"] = "ok" if not problems else "problems found"
    return report


def format_text(r: Dict[str, Any]) -> str:
    lines = ["PerFin environment check (no network calls)", "status: %s" % r["status"],
             "python: %s %s-bit" % (r["python"]["version"], r["python"]["bits"])]
    if r["status"] == "unsupported platform":
        lines.append("platform: %s - %s" % (r["platform"], r["detail"]))
        return "\n".join(lines)
    w = r["windows"]
    lines.append("windows: %s %s %s" % (w["release"], w["version"], w.get("edition") or ""))
    o = r["office"]
    lines.append("office click-to-run: %s" % (o.get("click_to_run") or "not found"))
    lines.append("office msi bitness: %s" % (o.get("msi_bitness") or "not found"))
    lines.append("access: %s" % o["access"])
    lines.append("ace oledb providers: %s" % (", ".join(o["ace_oledb_providers"]) or "none"))
    for k, v in r["odbc_drivers"].items():
        lines.append("odbc drivers (%s): %s" % (k, "unreadable" if v is None else ", ".join(v) or "none"))
    lines.append("pyodbc: %s" % ("installed %s" % r["pyodbc"].get("version") if r["pyodbc"]["installed"] else "not installed"))
    lines.append("primary adapter ready: %s" % r["primary_adapter"]["ready"])
    lines.extend("problem: %s" % p for p in r["problems"])
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    r = collect()
    print(json.dumps(r, indent=2, sort_keys=True) if "--json" in argv else format_text(r))
    if r["status"] == "unsupported platform":
        return EXIT_UNSUPPORTED
    return EXIT_OK if r["status"] == "ok" else EXIT_PROBLEM


if __name__ == "__main__":
    sys.exit(main())
