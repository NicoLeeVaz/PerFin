"""Static offline-compatibility inspection for PerFin workbooks, M queries and VBA text.

Runs on Linux on the workbook package (zip/XML) without Excel. It flags:

* external workbook links (xl/externalLinks, [n]Sheet!A1 references);
* data connections other than the Power Query workbook provider or a local
  Access/text file, and any web query;
* hyperlinks and other relationships to remote targets;
* dangerous or volatile formulas (WEBSERVICE, FILTERXML, RTD, CALL, REGISTER, IMAGE,
  STOCKHISTORY, PY, DDE, INDIRECT, OFFSET, NOW, RAND, HYPERLINK to a URL, ...);
* embedded Power Query (DataMashup) or .pq text using a non-local source;
* exported VBA text with network or process calls (XMLHTTP, WinHttp, URLDownloadToFile,
  Shell, ShellExecute, WScript.Shell, FollowHyperlink, mail objects, URLs) or any
  Declare outside a small allow-list;
* text cells that could become formulas without Excel's quote prefix (1c rule);
* add-in, ActiveX and OLE parts, and a VBA project inside an .xlsx.

It is a static guard, not proof of offline behaviour: Excel, add-ins and Office
settings can still reach the network. Those remain pending manual checks.
"""
import base64
import io
import posixpath
import re
import zipfile
from collections import namedtuple
from pathlib import Path
from xml.etree import ElementTree as ET

from ._deps import needs_formula_escape

Finding = namedtuple("Finding", "severity rule where detail")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

ALLOWED_FUNCTIONS = {"TODAY"}  # the only volatile function the core shell uses (staleness check)
NETWORK_FUNCTIONS = {"WEBSERVICE", "FILTERXML", "ENCODEURL", "RTD", "IMAGE", "STOCKHISTORY", "PY",
                     "TRANSLATE", "DETECTLANGUAGE", "COPILOT"}
CODE_FUNCTIONS = {"CALL", "REGISTER", "REGISTER.ID", "EXEC", "EXECUTE", "DDEINITIATE", "DDE"}
VOLATILE_FUNCTIONS = {"INDIRECT", "OFFSET", "NOW", "RAND", "RANDBETWEEN", "RANDARRAY", "INFO", "CELL"}
_FUNC = re.compile(r"(?<![A-Za-z0-9_.\[])((?:_xlfn\.|_xlws\.|_xludf\.)?[A-Za-z][A-Za-z0-9_.]*)\s*\(")
_STRING = re.compile(r'"(?:[^"]|"")*"')
_EXT_REF = re.compile(r"\[\d+\][^\]]*!|\[[^\]]+\.(?:xls[xmb]?|xlam|csv|ods)\]", re.I)
_DDE = re.compile(r"(?<![A-Za-z0-9_\]])[A-Za-z][A-Za-z0-9_.]*\|")
_REMOTE = re.compile(r"(?i)\b(?:https?|ftp|ftps|file|mailto|ms-[a-z-]+):|^\s*\\\\|^//")

# Local sources plus parsers of local binaries.
M_ALLOWED_SOURCES = {"File.Contents", "Folder.Files", "Folder.Contents", "Access.Database",
                     "Excel.CurrentWorkbook", "Csv.Document", "Json.Document", "Xml.Document"}
_M_SOURCE = re.compile(r"\b([A-Z][A-Za-z0-9]*\.(?:Contents|Database|Databases|Feed|Files|DataSource|Query|Tables|"
                       r"Page|BrowserContents|Headers|Document|Workbook|Execute|Sites|Files|Items|Roots|Views|"
                       r"Accounts|Container|Containers|Blobs))\s*\(")
_M_DENY = re.compile(r"\b(Web\.[A-Za-z]+|OData\.[A-Za-z]+|SharePoint\.[A-Za-z]+|Sql\.[A-Za-z]+|Odbc\.[A-Za-z]+|"
                     r"OleDb\.[A-Za-z]+|AzureStorage\.[A-Za-z]+|Salesforce[A-Za-z]*\.[A-Za-z]+|Exchange\.[A-Za-z]+|"
                     r"ActiveDirectory\.[A-Za-z]+|Python\.Execute|R\.Execute|Expression\.Evaluate|"
                     r"Cdm\.[A-Za-z]+|PowerPlatform\.[A-Za-z]+|Dataverse\.[A-Za-z]+|Snowflake\.[A-Za-z]+)\b")
_M_URL = re.compile(r'(?i)"(?:https?|ftp|ftps)://|"\\\\[A-Za-z0-9]')

VBA_DENY = [
    ("vba_network", re.compile(r"(?i)\b(?:MSXML2|XMLHTTP\w*|ServerXMLHTTP\w*|WinHttp\w*|URLDownloadToFile\w*|"
                               r"InternetOpen\w*|InternetReadFile|InternetConnect\w*|HttpOpenRequest\w*|"
                               r"HttpSendRequest\w*|urlmon|wininet|ws2_32|WinSock|InternetExplorer)\b")),
    ("vba_process", re.compile(r"(?i)\b(?:Shell|ShellExecute\w*|WScript\.\w+|Shell\.Application|"
                               r"CreateProcess\w*|WinExec)\b")),
    ("vba_hyperlink", re.compile(r"(?i)\bFollowHyperlink\b|\.Hyperlinks\.Add\b")),
    ("vba_mail", re.compile(r"(?i)\b(?:Outlook\.Application|CDO\.Message|MAPI\w*|SendMail|MailEnvelope)\b")),
    ("vba_object", re.compile(r"(?i)\b(?:CreateObject|GetObject)\s*\(")),
    ("vba_dynamic", re.compile(r"(?i)\b(?:Application\.Run|ExecuteExcel4Macro|CallByName|VBComponents|"
                               r"Workbooks\.OpenXML|Workbooks\.OpenText|Workbooks\.OpenDatabase)\b")),
    ("vba_url", re.compile(r"(?i)\"(?:[^\"]|\"\")*(?:https?|ftp|ftps)://|\"\\\\\\\\[A-Za-z0-9]")),
]
VBA_DECLARE_ALLOWED = {("ole32", "CoCreateGuid"), ("kernel32", "GetSystemTime")}
_DECLARE = re.compile(r'(?i)\bDeclare\s+(?:PtrSafe\s+)?(?:Function|Sub)\s+(\w+)\s+Lib\s+"([^"]+)"')


def _formula_findings(formula, where):
    out = []
    bare = _STRING.sub('""', formula)
    for m in _FUNC.finditer(bare):
        name = m.group(1).upper()
        for prefix in ("_XLFN.", "_XLWS.", "_XLUDF."):
            if name.startswith(prefix):
                if prefix == "_XLUDF.":
                    out.append(Finding("ERROR", "udf_formula", where, "user-defined/add-in function %s" % name))
                name = name[len(prefix):]
        if name in ALLOWED_FUNCTIONS:
            continue
        if name in NETWORK_FUNCTIONS:
            out.append(Finding("ERROR", "network_formula", where, "%s can reach the network" % name))
        elif name in CODE_FUNCTIONS:
            out.append(Finding("ERROR", "code_formula", where, "%s runs external code" % name))
        elif name in VOLATILE_FUNCTIONS:
            out.append(Finding("ERROR", "volatile_formula", where, "%s is volatile or can reference other files" % name))
        elif name == "HYPERLINK":
            args = formula[m.start():]
            if _REMOTE.search(args) or "://" in args or "\\\\" in args:
                out.append(Finding("ERROR", "remote_hyperlink_formula", where, "HYPERLINK to a remote target"))
            else:
                out.append(Finding("WARN", "hyperlink_formula", where, "HYPERLINK formula; check its target"))
    if _EXT_REF.search(bare):
        out.append(Finding("ERROR", "external_reference", where, "reference to another workbook"))
    if _DDE.search(bare):
        out.append(Finding("ERROR", "dde_formula", where, "DDE-style app|topic reference"))
    return out


def check_m_text(text, where):
    """Flag non-local Power Query sources in M text (comments removed first)."""
    code = _strip_m_comments(text)
    out = []
    for m in _M_DENY.finditer(code):
        out.append(Finding("ERROR", "m_non_local_source", where, "%s is not a local source" % m.group(1)))
    for m in _M_SOURCE.finditer(code):
        if m.group(1) not in M_ALLOWED_SOURCES and not _M_DENY.match(m.group(1)):
            out.append(Finding("ERROR", "m_unknown_source", where, "%s is not on the local-source allow-list"
                               % m.group(1)))
    if _M_URL.search(code):
        out.append(Finding("ERROR", "m_remote_literal", where, "URL or UNC path literal"))
    return out


def _strip_m_comments(text):
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    out.append('"')
                    i += 1
                else:
                    in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _strip_vba_comments(text):
    lines = []
    for line in text.splitlines():
        out, in_str = [], False
        stripped = line.lstrip()
        if re.match(r"(?i)rem\b", stripped):
            lines.append("")
            continue
        for ch in line:
            if ch == '"':
                in_str = not in_str
            elif ch == "'" and not in_str:
                break
            out.append(ch)
        lines.append("".join(out))
    return "\n".join(lines)


def check_vba_text(text, where):
    code = _strip_vba_comments(text)
    bare = _STRING.sub(lambda m: '"' + " " * (len(m.group()) - 2) + '"', code)  # keep offsets
    out = []
    for rule, rx in VBA_DENY:
        for m in rx.finditer(code if rule == "vba_url" else bare):
            line = code.count("\n", 0, m.start()) + 1
            out.append(Finding("ERROR", rule, "%s:%d" % (where, line), code[m.start():m.end()][:60]))
    for m in _DECLARE.finditer(code):
        lib = m.group(2).lower().removesuffix(".dll")
        if (lib, m.group(1)) not in VBA_DECLARE_ALLOWED:
            line = code.count("\n", 0, m.start()) + 1
            out.append(Finding("ERROR", "vba_declare", "%s:%d" % (where, line),
                               "Declare %s in %s is not allowed" % (m.group(1), m.group(2))))
    return out


def check_vba_dir(path):
    out = []
    for p in sorted(Path(path).rglob("*")):
        if p.suffix.lower() in (".bas", ".cls", ".frm"):
            out += check_vba_text(p.read_text(encoding="utf-8"), p.name)
    return out


def check_powerquery_dir(path):
    out = []
    for p in sorted(Path(path).rglob("*.pq")):
        out += check_m_text(p.read_text(encoding="utf-8"), str(p.relative_to(path)))
    return out


def _decode_xml_bytes(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def extract_mashup_formulas(item_xml_bytes):
    """Return the M section text from a DataMashup customXml part ([MS-QDEFF] layout)."""
    text = _decode_xml_bytes(item_xml_bytes)
    m = re.search(r"<DataMashup[^>]*>([^<]*)</DataMashup>", text)
    if not m:
        return None
    raw = base64.b64decode(m.group(1).strip())
    length = int.from_bytes(raw[4:8], "little")
    package = zipfile.ZipFile(io.BytesIO(raw[8:8 + length]))
    return "\n".join(package.read(n).decode("utf-8-sig") for n in package.namelist() if n.endswith(".m"))


def _local_path(target):
    return bool(re.match(r"^[A-Za-z]:\\", target or "")) and not (target or "").startswith("\\\\")


def _check_connections(xml, out):
    root = ET.fromstring(xml)
    for conn in root.findall("m:connection", NS):
        name = conn.get("name", "?")
        where = "connection %s" % name
        if conn.find("m:webPr", NS) is not None or conn.get("type") == "4":
            out.append(Finding("ERROR", "web_query", where, "web query connection"))
            continue
        odc = conn.get("odcFile")
        if odc and not _local_path(odc):
            out.append(Finding("ERROR", "data_connection", where, "connection file is not a local path"))
        db = conn.find("m:dbPr", NS)
        text = conn.find("m:textPr", NS)
        if db is not None:
            cs = db.get("connection", "")
            low = cs.lower()
            if "provider=microsoft.mashup.oledb.1" in low and "data source=$workbook$" in low:
                continue
            src = re.search(r"(?i)data source=([^;]+)", cs)
            if "provider=microsoft.ace.oledb" in low and src and _local_path(src.group(1).strip('"')) \
                    and src.group(1).lower().rstrip('"').endswith((".accdb", ".mdb")):
                continue
            out.append(Finding("ERROR", "data_connection", where, "only the Power Query workbook provider or a "
                                                                  "local Access file is allowed"))
        elif text is not None:
            if not _local_path(text.get("sourceFile", "")):
                out.append(Finding("ERROR", "data_connection", where, "text import from a non-local path"))
        else:
            out.append(Finding("ERROR", "data_connection", where, "unsupported connection type %s" % conn.get("type")))


def check_workbook(path):
    """Inspect an .xlsx/.xlsm package. Returns a list of Finding."""
    path = Path(path)
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for n in names:
            low = n.lower()
            if low.startswith("xl/externallinks/"):
                out.append(Finding("ERROR", "external_link", n, "external workbook link part"))
            elif low.startswith(("xl/activex/", "xl/embeddings/")):
                out.append(Finding("ERROR", "embedded_object", n, "ActiveX/OLE object"))
            elif low.startswith(("xl/webextensions/", "xl/webextension")):
                out.append(Finding("ERROR", "web_addin", n, "Office web add-in part"))
            elif low == "xl/vbaproject.bin":
                if path.suffix.lower() == ".xlsx":
                    out.append(Finding("ERROR", "vba_in_xlsx", n, "VBA project inside an .xlsx"))
                else:
                    out.append(Finding("INFO", "vba_project", n, "embedded VBA: scan the exported .bas text and run "
                                                                 "olevba on Windows (pending check)"))
            elif low.startswith("xl/connections.xml"):
                _check_connections(z.read(n), out)
            elif low.startswith("customxml/item") and low.endswith(".xml"):
                data = z.read(n)
                if b"DataMashup" in data or b"D\x00a\x00t\x00a\x00M\x00a\x00s\x00h\x00u\x00p" in data:
                    formulas = extract_mashup_formulas(data)
                    if formulas is not None:
                        out += check_m_text(formulas, n + " (Power Query)")
            if low.endswith(".rels"):
                _check_rels(z, n, out)
            if low.endswith(".xml") and (low.startswith("xl/worksheets/") or low == "xl/workbook.xml"):
                _check_part_formulas(z.read(n), n, out)
    out += _check_text_cells(path)
    return out


def _check_rels(z, name, out):
    root = ET.fromstring(z.read(name))
    for rel in root.findall(REL_NS + "Relationship"):
        if rel.get("TargetMode") != "External":
            continue
        target = rel.get("Target", "")
        if rel.get("Type", "").endswith("/hyperlink"):
            if _REMOTE.search(target) and not re.match(r"(?i)^file:///[A-Za-z]:/", target):
                out.append(Finding("ERROR", "remote_hyperlink", name, "hyperlink to %s" % target.split(":")[0]))
            else:
                out.append(Finding("WARN", "file_hyperlink", name, "hyperlink to a local file"))
        else:
            out.append(Finding("ERROR", "external_target", name, "external relationship %s"
                               % posixpath.basename(rel.get("Type", ""))))


def _check_part_formulas(xml, name, out):
    root = ET.fromstring(xml)
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("f", "formula", "formula1", "formula2", "definedName") and el.text:
            out += _formula_findings(el.text, name)


def _check_text_cells(path):
    from openpyxl import load_workbook
    out = []
    wb = load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "s" and isinstance(c.value, str) and needs_formula_escape(c.value) \
                        and not c.quotePrefix:
                    out.append(Finding("ERROR", "unescaped_text", "%s!%s" % (ws.title, c.coordinate),
                                       "text starting with a formula trigger lacks the quote prefix"))
    return out
