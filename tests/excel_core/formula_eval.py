"""A small evaluator for the formula subset the core workbook uses (tests only).

openpyxl stores formulas but does not calculate them, and the container has no Excel.
This evaluator implements the Excel semantics the shell depends on (SUMIFS/COUNTIFS
criteria with operators and wildcards, blank handling, lazy IF, mixed-type comparison)
so the Linux tests can check totals. It is not a substitute for desktop recalculation,
which stays a pending Windows check. Any unsupported construct raises, so the
workbook cannot quietly drift outside what is tested.
"""
import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal

from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

EPOCH = dt.datetime(1899, 12, 30)
FUNCTIONS = {"SUM", "SUMIFS", "COUNTIFS", "COUNTA", "COUNT", "MIN", "MAX", "IF", "AND", "OR", "ROUND", "INT",
             "LEFT", "TODAY"}

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<sref>(?:'[^']+'|[A-Za-z_][A-Za-z0-9_]*)!\$?[A-Z]{1,3}\$?\d+)
  | (?P<struct>[A-Za-z_][A-Za-z0-9_]*\[[A-Za-z0-9_]+\])
  | (?P<cell>\$?[A-Z]{1,3}\$?\d+(?![A-Za-z0-9_(]))
  | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
  | (?P<op><>|<=|>=|[-+*/&=<>(),])
""", re.X)


class FormulaError(Exception):
    pass


def serial(v):
    if isinstance(v, dt.datetime):
        return (v - EPOCH).total_seconds() / 86400.0
    if isinstance(v, dt.date):
        return float((v - EPOCH.date()).days)
    return v


def tokenize(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise FormulaError("cannot tokenize %r at %d" % (text, pos))
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
    return out


class Evaluator:
    def __init__(self, wb, today, overrides=None):
        self.wb, self.today = wb, today
        self.overrides = overrides or {}
        self.cache = {}
        self.tables = {}
        for ws in wb.worksheets:
            for name, ref in ws.tables.items():
                self.tables[name] = (ws, ref)
        self.names = {n: d.attr_text for n, d in wb.defined_names.items()}

    # ------------------------------------------------------------ cells
    def cell(self, sheet, coord):
        coord = coord.replace("$", "")
        key = (sheet, coord)
        if key in self.overrides:
            return self.overrides[key]
        if key in self.cache:
            return self.cache[key]
        c = self.wb[sheet][coord]
        if c.data_type == "f" or (isinstance(c.value, str) and c.data_type != "s" and c.value.startswith("=")):
            self.cache[key] = None
            v = self.evaluate(c.value, sheet)
        else:
            v = serial(c.value)
        self.cache[key] = v
        return v

    def name_ref(self, name):
        if name not in self.names:
            raise FormulaError("unknown name %s" % name)
        sheet, coord = self.names[name].rsplit("!", 1)
        return self.cell(sheet.strip("'"), coord)

    def column(self, table, col):
        if table not in self.tables:
            raise FormulaError("unknown table %s" % table)
        ws, ref = self.tables[table]
        a, b = ref.split(":")
        c1, r1 = coordinate_from_string(a)
        c2, r2 = coordinate_from_string(b)
        left, right = column_index_from_string(c1), column_index_from_string(c2)
        headers = [ws.cell(row=r1, column=j).value for j in range(left, right + 1)]
        if col not in headers:
            raise FormulaError("unknown column %s[%s]" % (table, col))
        j = left + headers.index(col)
        return [self.cell(ws.title, ws.cell(row=r, column=j).coordinate) for r in range(r1 + 1, r2 + 1)]

    # ------------------------------------------------------------ parse
    def evaluate(self, formula, sheet):
        if not formula.startswith("="):
            raise FormulaError("not a formula")
        saved = (getattr(self, "toks", None), getattr(self, "i", 0), getattr(self, "sheet", None))
        try:
            self.toks, self.i, self.sheet = tokenize(formula[1:]), 0, sheet
            node = self.parse_cmp()
            if self.i != len(self.toks):
                raise FormulaError("trailing tokens in %r" % formula)
            return self.run(node)
        finally:
            self.toks, self.i, self.sheet = saved

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise FormulaError("expected %s, found %s" % (value, tok[1]))
        self.i += 1
        return tok

    def parse_cmp(self):
        left = self.parse_concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            left = ("cmp", op, left, self.parse_concat())
        return left

    def parse_concat(self):
        left = self.parse_add()
        while self.peek()[1] == "&":
            self.take()
            left = ("cat", left, self.parse_add())
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            left = ("arith", op, left, self.parse_mul())
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            left = ("arith", op, left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.peek()[1] == "-":
            self.take()
            return ("neg", self.parse_unary())
        return self.parse_atom()

    def parse_atom(self):
        kind, text = self.take()
        if kind == "num":
            return ("lit", float(text) if "." in text else int(text))
        if kind == "str":
            return ("lit", text[1:-1].replace('""', '"'))
        if kind == "struct":
            t, c = text[:-1].split("[")
            return ("col", t, c)
        if kind == "cell":
            return ("ref", self.sheet, text)
        if kind == "sref":
            s, c = text.rsplit("!", 1)
            return ("ref", s.strip("'"), c)
        if kind == "op" and text == "(":
            node = self.parse_cmp()
            self.take(")")
            return node
        if kind == "name":
            up = text.upper()
            if self.peek()[1] == "(":
                if up not in FUNCTIONS:
                    raise FormulaError("unsupported function %s" % text)
                self.take("(")
                args = []
                if self.peek()[1] != ")":
                    args.append(self.parse_cmp())
                    while self.peek()[1] == ",":
                        self.take()
                        args.append(self.parse_cmp())
                self.take(")")
                return ("fn", up, args)
            if up in ("TRUE", "FALSE"):
                return ("lit", up == "TRUE")
            return ("name", text)
        raise FormulaError("unexpected token %r" % text)

    # ------------------------------------------------------------ run
    def run(self, n):
        k = n[0]
        if k == "lit":
            return n[1]
        if k == "ref":
            return self.cell(n[1], n[2])
        if k == "name":
            return self.name_ref(n[1])
        if k == "col":
            return self.column(n[1], n[2])
        if k == "neg":
            return -num(self.run(n[1]))
        if k == "arith":
            a, b = num(self.run(n[2])), num(self.run(n[3]))
            return {"+": a + b, "-": a - b, "*": a * b}[n[1]] if n[1] != "/" else a / b
        if k == "cat":
            return text(self.run(n[1])) + text(self.run(n[2]))
        if k == "cmp":
            return compare(n[1], self.run(n[2]), self.run(n[3]))
        if k == "fn":
            return self.call(n[1], n[2])
        raise FormulaError(k)

    def call(self, f, args):
        if f == "IF":
            cond = self.run(args[0])
            branch = args[1] if truthy(cond) else (args[2] if len(args) > 2 else ("lit", False))
            return self.run(branch)
        if f == "TODAY":
            return serial(self.today)
        vals = [self.run(a) for a in args]
        if f in ("SUM", "COUNT", "MIN", "MAX", "COUNTA"):
            flat = [x for v in vals for x in (v if isinstance(v, list) else [v])]
            nums = [x for x in flat if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if f == "SUM":
                return sum(nums)
            if f == "COUNT":
                return len(nums)
            if f == "COUNTA":
                return len([x for x in flat if x is not None])
            return (min if f == "MIN" else max)(nums) if nums else 0
        if f == "SUMIFS":
            rng, pairs = vals[0], vals[1:]
            mask = self.mask(pairs, len(rng))
            return sum(v for v, ok in zip(rng, mask) if ok and isinstance(v, (int, float)) and not isinstance(v, bool))
        if f == "COUNTIFS":
            return sum(self.mask(vals, len(vals[0])))
        if f == "AND":
            return all(truthy(v) for v in vals)
        if f == "OR":
            return any(truthy(v) for v in vals)
        if f == "ROUND":
            q = Decimal(1).scaleb(-int(vals[1]))
            return float(Decimal(str(num(vals[0]))).quantize(q, rounding=ROUND_HALF_UP))
        if f == "INT":
            import math
            return math.floor(num(vals[0]))
        if f == "LEFT":
            return text(vals[0])[: int(vals[1]) if len(vals) > 1 else 1]
        raise FormulaError(f)

    def mask(self, pairs, n):
        if len(pairs) % 2:
            raise FormulaError("criteria must come in pairs")
        mask = [True] * n
        for rng, crit in zip(pairs[0::2], pairs[1::2]):
            if not isinstance(rng, list) or len(rng) != n:
                raise FormulaError("criteria ranges must be table columns of equal size")
            mask = [m and matches(v, crit) for m, v in zip(mask, rng)]
        return mask


def truthy(v):
    if isinstance(v, str):
        raise FormulaError("#VALUE! text used as a condition")
    return bool(v)


def num(v):
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    raise FormulaError("#VALUE! arithmetic on text %r" % (v,))


def text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _rank(v):
    return 2 if isinstance(v, bool) else 1 if isinstance(v, str) else 0


def compare(op, a, b):
    if a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0)
    if b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0)
    if _rank(a) != _rank(b):
        ka, kb = _rank(a), _rank(b)
    elif isinstance(a, str):
        ka, kb = a.casefold(), b.casefold()
    else:
        ka, kb = a, b
    return {"=": ka == kb, "<>": ka != kb, "<": ka < kb, ">": ka > kb, "<=": ka <= kb, ">=": ka >= kb}[op]


def _wild(pattern):
    out, i = "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern):
            out += re.escape(pattern[i + 1])
            i += 2
            continue
        out += ".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
        i += 1
    return re.compile("^" + out + "$", re.S | re.I)


def matches(cell, crit):
    """Excel criteria semantics for SUMIFS/COUNTIFS (the subset the workbook uses)."""
    if isinstance(crit, bool):
        return isinstance(cell, bool) and cell == crit
    if isinstance(crit, (int, float)):
        return isinstance(cell, (int, float)) and not isinstance(cell, bool) and cell == crit
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", crit, re.S)
    op, operand = m.group(1) or "", m.group(2)
    blank = cell is None or cell == ""
    if operand == "":
        if op == "<>":
            return not blank
        return blank
    try:
        number = float(operand)
    except ValueError:
        number = None
    is_num = isinstance(cell, (int, float)) and not isinstance(cell, bool)
    if number is not None:
        if not is_num:
            return op == "<>"
        return compare(op or "=", cell, number)
    if operand.upper() in ("TRUE", "FALSE") and op in ("", "=", "<>"):
        eq = isinstance(cell, bool) and cell == (operand.upper() == "TRUE")
        return not eq if op == "<>" else eq
    hit = isinstance(cell, str) and bool(_wild(operand).match(cell))
    if op == "<>":
        return not hit
    if op in ("", "="):
        return hit
    raise FormulaError("text range criteria are not used by the workbook")
