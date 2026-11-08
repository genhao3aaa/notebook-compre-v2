"""LaTeX 数学公式的最小解析器与 Markdown 公式扫描。

阅读器要能显示笔记里常见的 $...$ / $$...$$ 公式。引入 MathJax 或
matplotlib 会破坏「零新依赖」的约束，所以这里自己解析一个 LaTeX 子集：
分式、根式、上下标、求和 / 积分、自动括号、矩阵、常用希腊字母与运算符。

本模块只做「文本 → 语法树 / 片段」，不 import Qt；排版与绘制在
src/ui/math_render.py。解析失败时退化成原始文本，绝不抛给界面。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

_ORD = "ord"
_BIN = "bin"
_REL = "rel"
_OPEN = "open"
_CLOSE = "close"
_PUNCT = "punct"
_OP = "op"


@dataclass(frozen=True)
class Sym:
    """一个字形（或一段正体文字）。style: math / it / up / bf / text。"""
    text: str
    style: str = "math"
    cls: str = _ORD


@dataclass(frozen=True)
class Space:
    em: float


@dataclass(frozen=True)
class LineBreak:
    """公式内的换行（顶层 ``\\\\`` 或作者写的 ``<br>``）。"""


@dataclass(frozen=True)
class Seq:
    items: Tuple[object, ...] = ()


@dataclass(frozen=True)
class Frac:
    num: Seq
    den: Seq
    bar: bool = True     # False：二项式系数（无横线）


@dataclass(frozen=True)
class Sqrt:
    body: Seq
    index: Optional[Seq] = None


@dataclass(frozen=True)
class Script:
    base: object
    sup: Optional[Seq] = None
    sub: Optional[Seq] = None


@dataclass(frozen=True)
class Accent:
    kind: str          # hat / bar / vec / dot / ddot / tilde / overline / underline
    body: Seq


@dataclass(frozen=True)
class Boxed:
    """\boxed{...}：给公式套一个方框（结论 / 最终式子常用）。"""

    body: Seq


@dataclass(frozen=True)
class Delim:
    left: str
    right: str
    body: Seq


@dataclass(frozen=True)
class Func:
    """函数名（log / sin / exp / operatorname）：正体，后面留一个细空格。"""
    text: str


@dataclass(frozen=True)
class BigOp:
    text: str
    limits: bool = False   # True: 上下限；False: 积分一类的右侧上下标


@dataclass(frozen=True)
class Matrix:
    rows: Tuple[Tuple[Seq, ...], ...]
    env: str = "matrix"


@dataclass(frozen=True)
class MathSegment:
    """一段行内 / 行间公式在原文中的位置与替换标记。"""
    start: int
    end: int
    source: str
    display: bool
    token: str


_GREEK: Dict[str, str] = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο",
    "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ",
    "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "ϕ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

_SYMBOLS: Dict[str, Tuple[str, str]] = {
    "le": ("≤", _REL), "leq": ("≤", _REL), "ge": ("≥", _REL),
    "geq": ("≥", _REL), "ne": ("≠", _REL), "neq": ("≠", _REL),
    "approx": ("≈", _REL), "equiv": ("≡", _REL), "sim": ("∼", _REL),
    "simeq": ("≃", _REL), "cong": ("≅", _REL), "propto": ("∝", _REL),
    "in": ("∈", _REL), "notin": ("∉", _REL), "ni": ("∋", _REL),
    "subset": ("⊂", _REL), "subseteq": ("⊆", _REL),
    "supset": ("⊃", _REL), "supseteq": ("⊇", _REL),
    "perp": ("⊥", _REL), "parallel": ("∥", _REL),
    "to": ("→", _REL), "rightarrow": ("→", _REL), "leftarrow": ("←", _REL),
    "leftrightarrow": ("↔", _REL), "Rightarrow": ("⇒", _REL),
    "Leftarrow": ("⇐", _REL), "Leftrightarrow": ("⇔", _REL),
    "longrightarrow": ("⟶", _REL), "longleftarrow": ("⟵", _REL),
    "longleftrightarrow": ("⟷", _REL),
    "Longrightarrow": ("⟹", _REL), "Longleftarrow": ("⟸", _REL),
    "Longleftrightarrow": ("⟺", _REL),
    "rightleftharpoons": ("⇌", _REL), "leftrightharpoons": ("⇋", _REL),
    "rightleftarrows": ("⇄", _REL), "leftrightarrows": ("⇆", _REL),
    "hookrightarrow": ("↪", _REL), "hookleftarrow": ("↩", _REL),
    "uparrow": ("↑", _REL), "downarrow": ("↓", _REL),
    "Uparrow": ("⇑", _REL), "Downarrow": ("⇓", _REL),
    "nearrow": ("↗", _REL), "searrow": ("↘", _REL),
    "swarrow": ("↙", _REL), "nwarrow": ("↖", _REL),
    "iff": ("⇔", _REL), "implies": ("⇒", _REL), "mapsto": ("↦", _REL),
    "mid": ("∣", _REL), "ll": ("≪", _REL), "gg": ("≫", _REL),
    "because": ("∵", _REL), "therefore": ("∴", _REL),
    "times": ("×", _BIN), "div": ("÷", _BIN), "cdot": ("·", _BIN),
    "pm": ("±", _BIN), "mp": ("∓", _BIN), "cup": ("∪", _BIN),
    "cap": ("∩", _BIN), "vee": ("∨", _BIN), "wedge": ("∧", _BIN),
    "land": ("∧", _BIN), "lor": ("∨", _BIN), "oplus": ("⊕", _BIN),
    "otimes": ("⊗", _BIN), "ast": ("∗", _BIN),
    "infty": ("∞", _ORD), "partial": ("∂", _ORD), "nabla": ("∇", _ORD),
    "forall": ("∀", _ORD), "exists": ("∃", _ORD), "neg": ("¬", _ORD),
    "emptyset": ("∅", _ORD), "varnothing": ("∅", _ORD),
    "angle": ("∠", _ORD), "triangle": ("△", _ORD),
    "aleph": ("ℵ", _ORD), "hbar": ("ℏ", _ORD), "ell": ("ℓ", _ORD),
    "Re": ("ℜ", _ORD), "Im": ("ℑ", _ORD), "wp": ("℘", _ORD),
    "prime": ("′", _ORD), "degree": ("°", _ORD), "circ": ("∘", _ORD),
    "cdots": ("⋯", _ORD), "ldots": ("…", _ORD), "dots": ("…", _ORD),
    "vdots": ("⋮", _ORD), "ddots": ("⋱", _ORD),
    "langle": ("⟨", _OPEN), "rangle": ("⟩", _CLOSE),
    "lfloor": ("⌊", _OPEN), "rfloor": ("⌋", _CLOSE),
    "lceil": ("⌈", _OPEN), "rceil": ("⌉", _CLOSE),
    "vert": ("|", _ORD), "Vert": ("‖", _ORD),
}

_FUNCS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos",
    "arctan", "sinh", "cosh", "tanh", "coth", "log", "ln", "lg",
    "exp", "arg", "deg", "dim", "ker", "hom", "det", "gcd", "Pr",
}

_BIG_OPS: Dict[str, Tuple[str, bool]] = {
    "sum": ("∑", True), "prod": ("∏", True), "coprod": ("∐", True),
    "bigcup": ("⋃", True), "bigcap": ("⋂", True),
    "bigoplus": ("⊕", True), "bigotimes": ("⊗", True),
    "int": ("∫", False), "iint": ("∬", False), "iiint": ("∭", False),
    "oint": ("∮", False),
}

_LIMIT_OPS = {"lim", "max", "min", "sup", "inf", "limsup", "liminf",
              "argmax", "argmin", "det", "gcd"}

_SPACES: Dict[str, float] = {
    ",": 0.167, ":": 0.222, ";": 0.278, "!": -0.167,
    "quad": 1.0, "qquad": 2.0, " ": 0.333, "enspace": 0.5,
    "thinspace": 0.167, "medspace": 0.222, "thickspace": 0.278,
}

_DELIMS: Dict[str, str] = {
    "(": "(", ")": ")", "[": "[", "]": "]",
    "{": "{", "}": "}", "|": "|", ".": "",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋",
    "lceil": "⌈", "rceil": "⌉", "vert": "|", "Vert": "‖",
    "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
}

ENV_DELIMS: Dict[str, Tuple[str, str]] = {
    "matrix": ("", ""), "smallmatrix": ("", ""),
    "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"),
    "Vmatrix": ("‖", "‖"), "cases": ("{", ""),
    "array": ("", ""), "aligned": ("", ""), "align": ("", ""),
    "align*": ("", ""), "gathered": ("", ""), "split": ("", ""),
}

_BIN_CHARS = set("+−-±∓×÷·∗∪∩∨∧⊕⊗⊙")
_REL_CHARS = set("=<>≤≥≠≈≡∼≃≅∝∈∉∋⊂⊃⊆⊇⊥∥→←↔⇒⇐⇔↦∣")
_OPEN_CHARS = set("([{⟨⌊⌈")
_CLOSE_CHARS = set(")]}⟩⌋⌉")
_PUNCT_CHARS = set(",;:")

_BLACKBOARD = {"R": "ℝ", "C": "ℂ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ",
               "P": "ℙ", "H": "ℍ", "B": "𝔹", "E": "𝔼", "F": "𝔽"}

_TOKEN_RE = re.compile(r"\\([A-Za-z]+|.)|([{}^_&])|(\s+)|(.)", re.S)
_TICK = chr(96)
_FENCE_RE = re.compile(r"^(" + _TICK + r"{3,}|~{3,})")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
#: 作者在公式里写的 HTML 换行：<br> / <br/> / <\mathrm{br}>
_BR_RE = re.compile(r"<\s*(?:\\mathrm\{br\}|br\s*/?)\s*>", re.I)


class _ParseError(Exception):
    pass


def _tokenize(src: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(src):
        cmd, struct, ws, ch = m.group(1), m.group(2), m.group(3), m.group(4)
        if cmd is not None:
            out.append(("cmd", cmd))
        elif struct is not None:
            out.append(({"{": "open", "}": "close", "^": "sup",
                         "_": "sub", "&": "amp"}[struct], ""))
        elif ws is not None:
            out.append(("ws", ws))
        else:
            out.append(("char", ch))
    return out


def _char_cls(ch: str) -> str:
    if ch in _BIN_CHARS:
        return _BIN
    if ch in _REL_CHARS:
        return _REL
    if ch in _OPEN_CHARS:
        return _OPEN
    if ch in _CLOSE_CHARS:
        return _CLOSE
    if ch in _PUNCT_CHARS:
        return _PUNCT
    return _ORD


def _make_char(ch: str) -> object:
    if ch == "-":
        ch = "−"
    elif ch == "*":
        ch = "∗"
    elif ch == "~":
        return Space(0.333)
    elif ch == "'":
        return Sym("′", "up")
    return Sym(ch, "math", _char_cls(ch))


def _restyle(node: object, style: str) -> object:
    """把 mathbf / mathrm 之类的样式递归套到子树里的字形上。"""
    if isinstance(node, Sym):
        if style == "bb":
            chars = "".join(_BLACKBOARD.get(c, c) for c in node.text)
            return Sym(chars, "up", node.cls)
        return Sym(node.text, style, node.cls)
    if isinstance(node, Seq):
        return Seq(tuple(_restyle(x, style) for x in node.items))
    if isinstance(node, Frac):
        return Frac(_restyle(node.num, style), _restyle(node.den, style),
                    node.bar)
    if isinstance(node, Sqrt):
        return Sqrt(_restyle(node.body, style),
                    _restyle(node.index, style) if node.index else None)
    if isinstance(node, Script):
        return Script(_restyle(node.base, style),
                      _restyle(node.sup, style) if node.sup else None,
                      _restyle(node.sub, style) if node.sub else None)
    if isinstance(node, Func):
        return node
    if isinstance(node, Accent):
        return Accent(node.kind, _restyle(node.body, style))
    if isinstance(node, Boxed):
        return Boxed(_restyle(node.body, style))
    if isinstance(node, Delim):
        return Delim(node.left, node.right, _restyle(node.body, style))
    if isinstance(node, Matrix):
        return Matrix(tuple(tuple(_restyle(c, style) for c in row)
                            for row in node.rows), node.env)
    return node


class _Parser:
    def __init__(self, src: str) -> None:
        self.toks = _tokenize(src)
        self.i = 0
        self.depth = 0

    def _peek(self) -> Optional[Tuple[str, str]]:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _next(self) -> Optional[Tuple[str, str]]:
        tok = self._peek()
        if tok is not None:
            self.i += 1
        return tok

    def _is_stop(self, tok: Optional[Tuple[str, str]],
                 stops: Sequence[str]) -> bool:
        if tok is None:
            return True
        kind, val = tok
        if kind == "close":
            return "}" in stops
        if kind == "char":
            return val in stops
        if kind == "amp":
            return "&" in stops
        if kind == "cmd":
            return val in stops
        return False

    def parse(self) -> Seq:
        return self._parse_list(())

    def _parse_list(self, stops: Sequence[str]) -> Seq:
        self.depth += 1
        if self.depth > 64:
            raise _ParseError("嵌套过深")
        out: List[object] = []
        try:
            while True:
                tok = self._peek()
                if self._is_stop(tok, stops):
                    break
                node = self._parse_atom()
                if node is None:
                    continue
                node = self._parse_scripts(node)
                if node is not None:
                    out.append(node)
        finally:
            self.depth -= 1
        return Seq(tuple(out))

    def _parse_scripts(self, base: object) -> object:
        sup: Optional[Seq] = None
        sub: Optional[Seq] = None
        while True:
            tok = self._peek()
            if tok is None:
                break
            if tok[0] == "sup":
                self._next()
                sup = self._parse_arg()
            elif tok[0] == "sub":
                self._next()
                sub = self._parse_arg()
            elif tok == ("char", "'"):
                self._next()
                prime = Seq((Sym("′", "up"),))
                sup = Seq(sup.items + prime.items) if sup else prime
            else:
                break
        if sup is None and sub is None:
            return base
        return Script(base, sup, sub)

    def _parse_arg(self) -> Seq:
        tok = self._peek()
        if tok is not None and tok[0] == "open":
            self._next()
            body = self._parse_list(("}",))
            if self._peek() is not None and self._peek()[0] == "close":
                self._next()
            return body
        node = self._parse_atom()
        if node is None:
            return Seq(())
        # 只取一个原子：x_1^2 的两个脚本都属于 x，不能被 1 抢走
        return Seq((node,))

    def _raw_group(self, strip: bool = True) -> str:
        """读取花括号里的原始文字（text 命令用），保留空格。"""
        tok = self._peek()
        if tok is None or tok[0] != "open":
            return ""
        self._next()
        depth = 1
        parts: List[str] = []
        while True:
            tok = self._next()
            if tok is None:
                break
            kind, val = tok
            if kind == "open":
                depth += 1
                parts.append("{")
            elif kind == "close":
                depth -= 1
                if depth == 0:
                    break
                parts.append("}")
            elif kind == "ws":
                if not parts or parts[-1] != " ":
                    parts.append(" ")
            elif kind == "cmd":
                parts.append(" " if val == "\\" else val)
            else:
                parts.append(val)
        text = "".join(parts)
        return text.strip() if strip else text

    def _read_delim(self) -> str:
        tok = self._next()
        if tok is None:
            return ""
        kind, val = tok
        if kind == "char":
            return _DELIMS.get(val, val)
        if kind == "cmd":
            return _DELIMS.get(val, "")
        return ""

    def _parse_atom(self) -> Optional[object]:
        tok = self._next()
        if tok is None:
            return None
        kind, val = tok

        if kind == "ws":
            return None
        if kind == "open":
            body = self._parse_list(("}",))
            if self._peek() is not None and self._peek()[0] == "close":
                self._next()
            return body
        if kind == "close":
            return None
        if kind == "sup" or kind == "sub":
            return None
        if kind == "amp":
            return Space(0.5)
        if kind == "char":
            return _make_char(val)

        name = val
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            return Frac(self._parse_arg(), self._parse_arg())
        if name in ("binom", "dbinom", "tbinom"):
            return Delim("(", ")", Seq((
                Frac(self._parse_arg(), self._parse_arg(), bar=False),)))
        if name == "sqrt":
            index = None
            if self._peek() == ("char", "["):
                self._next()
                index = self._parse_list(("]",))
                if self._peek() == ("char", "]"):
                    self._next()
            return Sqrt(self._parse_arg(), index)
        if name == "left":
            left = self._read_delim()
            body = self._parse_list(("right",))
            if self._peek() == ("cmd", "right"):
                self._next()
            right = self._read_delim()
            return Delim(left, right, body)
        if name == "right":
            return None
        if name == "begin":
            return self._parse_env()
        if name == "end":
            self._raw_group()
            return None
        if name in ("text", "mbox", "textnormal", "textrm"):
            return Seq((Sym(self._raw_group(strip=False), "text"),))
        if name in ("mathbf", "boldsymbol", "bm"):
            return _restyle(self._parse_arg(), "bf")
        if name == "operatorname":
            return Func(self._raw_group())
        if name in ("mathrm", "mathsf", "mathtt"):
            return _restyle(self._parse_arg(), "up")
        if name in ("mathit", "mathcal", "mathscr", "mathfrak"):
            return _restyle(self._parse_arg(), "it")
        if name == "mathbb":
            return _restyle(self._parse_arg(), "bb")
        if name in ("hat", "widehat"):
            return Accent("hat", self._parse_arg())
        if name in ("bar", "overline"):
            return Accent("bar", self._parse_arg())
        if name in ("vec", "overrightarrow"):
            return Accent("vec", self._parse_arg())
        if name in ("dot", "ddot", "tilde", "widetilde"):
            return Accent(name, self._parse_arg())
        if name == "underline":
            return Accent("underline", self._parse_arg())
        if name in ("boxed", "fbox"):
            return Boxed(self._parse_arg())
        if name in ("big", "Big", "bigg", "Bigg", "bigl", "Bigl",
                    "biggl", "Biggl", "bigr", "Bigr", "biggr", "Biggr",
                    "displaystyle", "textstyle"):
            return None
        if name in _BIG_OPS:
            text, limits = _BIG_OPS[name]
            return BigOp(text, limits)
        if name in _LIMIT_OPS:
            return BigOp(name, True)
        if name in _FUNCS:
            return Func(name)
        if name in _GREEK:
            ch = _GREEK[name]
            style = "up" if ch.isupper() else "math"
            return Sym(ch, style, _ORD)
        if name in _SYMBOLS:
            ch, cls = _SYMBOLS[name]
            return Sym(ch, "math", cls)
        if name in _SPACES:
            return Space(_SPACES[name])
        if name in _DELIMS:
            ch = _DELIMS[name]
            return Sym(ch, "up", _char_cls(ch)) if ch else None
        if name == "\\":
            return LineBreak()
        if len(name) == 1:
            return _make_char(name)
        return Sym(name, "up")

    def _parse_env(self) -> object:
        env = self._raw_group()
        nxt = self._peek()
        if env == "array" and nxt is not None and nxt[0] == "open":
            self._raw_group()          # 列格式 {cc}：不参与排版
        rows: List[List[Seq]] = []
        row: List[Seq] = []
        while True:
            cell = self._parse_list(("&", "\\", "end"))
            row.append(cell)
            tok = self._peek()
            if tok is None:
                break
            if tok[0] == "amp":
                self._next()
                continue
            if tok == ("cmd", "\\"):
                self._next()
                rows.append(row)
                row = []
                continue
            if tok == ("cmd", "end"):
                self._next()
                self._raw_group()
                break
            break
        if row and (len(row) > 1 or row[0].items):
            rows.append(row)
        if not rows:
            rows = [[Seq(())]]
        width = max(len(r) for r in rows)
        norm = tuple(tuple(r + [Seq(())] * (width - len(r))) for r in rows)
        return Matrix(norm, env)


def parse_math(source: str) -> Seq:
    """把一段 LaTeX 子集解析成语法树；任何异常都退化为原始文字。"""
    src = _BR_RE.sub(lambda _m: " " + chr(92) * 2 + " ",
                     source or "").strip()
    if not src:
        return Seq(())
    if len(src) > 4000:
        return Seq((Sym(src, "text"),))
    try:
        return _Parser(src).parse()
    except Exception:                 # pragma: no cover - 防御性
        return Seq((Sym(src, "text"),))


# ---------------------------------------------------------------------- #
# 纯文字降级：目录 / 工具提示 / 无障碍
# ---------------------------------------------------------------------- #
_SUB_MAP = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆",
    "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍",
    ")": "₎", "−": "₋", "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ",
    "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ", "α": "ᵅ", "β": "ᵝ", "γ": "ᵞ",
    "ρ": "ᵨ", "φ": "ᵩ", "χ": "ᵪ",
}
_SUP_MAP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
    "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽",
    ")": "⁾", "−": "⁻", "i": "ⁱ", "n": "ⁿ",
}
_PLAIN_DELIMS = {"(": ")", "[": "]", "{": "}", "|": "|", "⟨": "⟩"}


def _plain_cls(node: object) -> str:
    if isinstance(node, Sym):
        return node.cls
    if isinstance(node, (Func, BigOp)):
        return "op"
    if isinstance(node, Script):
        return _plain_cls(node.base)
    return "ord"


def _plain_seq(node: Seq) -> str:
    """纯文字也要保留二元 / 关系符两侧的空格，否则 Kₐ≥10⁵ 会挤成一团。"""
    out: List[str] = []
    prev: Optional[str] = None
    for item in node.items:
        text = _plain_node(item)
        if not text:
            continue
        cls = _plain_cls(item)
        # 一元正负号（开头 / 括号或运算符之后）两侧都不留空格
        unary = cls == _BIN and (prev is None
                                 or prev in (_OPEN, _REL, _BIN, _PUNCT, _OP))
        eff = _ORD if unary else cls
        sep = ""
        if prev is not None and (eff in (_BIN, _REL) or prev in (_BIN, _REL, _PUNCT)):
            sep = " "
        out.append(sep + text)
        prev = eff
    return "".join(out)


def _plain_script(node: Optional[Seq], table: Dict[str, str],
                  mark: str) -> str:
    if node is None:
        return ""
    text = _plain_seq(node).strip()
    if not text:
        return ""
    compact = text.replace(" ", "")
    mapped = "".join(table.get(ch, "") for ch in compact)
    if len(mapped) == len(compact):
        return mapped
    return mark + "(" + text + ")"


def _plain_node(node: object) -> str:
    if isinstance(node, Sym):
        return node.text
    if isinstance(node, Space):
        return " " if node.em > 0 else ""
    if isinstance(node, LineBreak):
        return " "
    if isinstance(node, Func):
        return node.text
    if isinstance(node, BigOp):
        return node.text
    if isinstance(node, Seq):
        return _plain_seq(node)
    if isinstance(node, Script):
        base = _plain_node(node.base)
        return (base + _plain_script(node.sub, _SUB_MAP, "_")
                + _plain_script(node.sup, _SUP_MAP, "^"))
    if isinstance(node, Frac):
        num = _plain_seq(node.num).strip()
        den = _plain_seq(node.den).strip()
        if len(node.num.items) > 1:
            num = "(" + num + ")"
        if len(node.den.items) > 1:
            den = "(" + den + ")"
        return num + "/" + den
    if isinstance(node, Sqrt):
        body = _plain_seq(node.body).strip()
        if node.index is not None:
            return "√[" + _plain_seq(node.index).strip() + "](" + body + ")"
        return "√(" + body + ")"
    if isinstance(node, Delim):
        return node.left + _plain_seq(node.body) + node.right
    if isinstance(node, Accent):
        return _plain_seq(node.body)
    if isinstance(node, Boxed):
        return _plain_seq(node.body)
    if isinstance(node, Matrix):
        rows = [" ".join(_plain_seq(cell).strip() for cell in row)
                for row in node.rows]
        body = "; ".join(r for r in rows if r)
        left, right = ENV_DELIMS.get(node.env, ("", ""))
        if not left and not right:
            return body
        if left in _PLAIN_DELIMS:
            right = _PLAIN_DELIMS[left]
        return left + body + right
    return ""


def math_to_plain(source: str) -> str:
    """把公式压成一行可读文字（Unicode 上下标，失败时退回 _ / ^ 记法）。

    只用于目录、工具提示这类没有排版能力的地方；文档正文仍然走
    src/ui/math_render.py 的真实矢量排版。
    """
    try:
        text = _plain_seq(parse_math(source or ""))
    except Exception:                 # pragma: no cover - 防御性
        return (source or "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _protected_mask(text: str) -> bytearray:
    """标出代码块 / 行内代码：这些位置里的美元符号不是公式。"""
    n = len(text)
    mask = bytearray(n)
    pos = 0
    fence: Optional[str] = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        m = _FENCE_RE.match(stripped)
        if fence is not None:
            for k in range(pos, pos + len(line)):
                mask[k] = True
            if m and m.group(1)[0] == fence[0]:
                fence = None
        elif m:
            fence = m.group(1)
            for k in range(pos, pos + len(line)):
                mask[k] = True
        elif (line.startswith("    ") or line.startswith("\t")) and line.strip():
            for k in range(pos, pos + len(line)):
                mask[k] = True
        pos += len(line)

    i = 0
    while i < n:
        if mask[i] or text[i] != _TICK:
            i += 1
            continue
        j = i
        while j < n and text[j] == _TICK:
            j += 1
        ticks = text[i:j]
        k = j
        while k < n and not mask[k]:
            if text[k] == "\n" and _BLANK_LINE_RE.match(text, k):
                break
            if text.startswith(ticks, k):
                break
            k += 1
        if k < n and text.startswith(ticks, k):
            end = k + len(ticks)
            for q in range(i, end):
                mask[q] = True
            i = end
        else:
            i = j
    return mask


def _escaped(text: str, i: int) -> bool:
    back = 0
    j = i - 1
    while j >= 0 and text[j] == "\\":
        back += 1
        j -= 1
    return back % 2 == 1


def _find_close(text: str, mask: bytearray, start: int, delim: str,
                display: bool) -> int:
    i = start
    n = len(text)
    while i < n:
        if mask[i]:
            return -1
        if text.startswith(delim, i) and not _escaped(text, i):
            return i
        if not display and text[i] == "\n" and _BLANK_LINE_RE.match(text, i):
            return -1
        i += 1
    return -1


def mask_math(text: str) -> Tuple[str, List[MathSegment]]:
    """把原文里的公式替换成占位符，返回 (掩码文本, 片段列表)。

    占位符用 Unicode 私用区字符，Markdown 不会改写它；界面层再按占位符
    把公式对象插回文档。
    """
    if not text:
        return text, []
    # 绝大多数 Markdown 没有公式：先做一次廉价的字符探测，避免整篇逐字扫描
    if "$" not in text and "\\(" not in text and "\\[" not in text:
        return text, []
    mask = _protected_mask(text)
    segs: List[MathSegment] = []
    out: List[str] = []
    copied = 0
    i = 0
    n = len(text)
    while i < n:
        if mask[i]:
            i += 1
            continue
        start = i
        display = False
        if text.startswith("$$", i) and not _escaped(text, i):
            display = True
            close = _find_close(text, mask, i + 2, "$$", True)
            if close < 0:
                i += 2
                continue
            body_start, body_end, end = i + 2, close, close + 2
        elif text[i] == "$" and not _escaped(text, i):
            close = _find_close(text, mask, i + 1, "$", False)
            if close <= i + 1:
                i += 1
                continue
            if text[i + 1].isspace() or text[close - 1].isspace():
                i += 1
                continue
            body_start, body_end, end = i + 1, close, close + 1
        elif text.startswith("\\(", i) and not _escaped(text, i):
            close = _find_close(text, mask, i + 2, "\\)", False)
            if close < 0:
                i += 2
                continue
            body_start, body_end, end = i + 2, close, close + 2
        elif text.startswith("\\[", i) and not _escaped(text, i):
            display = True
            close = _find_close(text, mask, i + 2, "\\]", True)
            if close < 0:
                i += 2
                continue
            body_start, body_end, end = i + 2, close, close + 2
        else:
            i += 1
            continue

        body = text[body_start:body_end].strip()
        if not body:
            i = end
            continue
        token = "\ue000%d\ue001" % len(segs)
        segs.append(MathSegment(start=start, end=end, source=body,
                                display=display, token=token))
        out.append(text[copied:start])
        out.append(token)
        copied = end
        i = end
    if not segs:
        return text, []
    out.append(text[copied:])
    return "".join(out), segs
