#!/usr/bin/env python3
"""A small, dependency-free reader for the YAML a letters repository writes.

Lifehug is deliberately dependency-free at runtime (docs/BUILDING.md §3), and
`lifehug_core.split_frontmatter` only reads the one-line JSON values Lifehug
itself emits. The documents writer (lifehug#471) has to read two files it did
not write: each transcript's YAML header (PyYAML ``safe_dump`` output, with
long strings wrapped across lines) and the hand-written ``people.yaml`` (block
lists of mappings, flow lists, flow mappings, comments).

This module reads exactly that subset and refuses the rest:

* block mappings and block sequences, including the indentless ``key:\\n- a``
  sequence ``safe_dump`` writes and ``- key: value`` mappings inside a list;
* flow sequences and flow mappings (``[a, "b", {p: x, in: [c]}]``), on one
  line or several;
* plain, single-quoted and double-quoted scalars, each possibly folded over
  several lines, with YAML's line-folding and double-quote escapes;
* ``#`` comments.

Anchors, aliases, tags, block scalars (``|`` / ``>``), multi-document
streams and complex keys raise :class:`YamlSubsetError` rather than being read
approximately: a header this reader cannot read exactly is a header the writer
must not file.

Plain scalars resolve the way PyYAML's ``safe_load`` resolves them (null,
YAML 1.1 booleans, ints, floats) EXCEPT timestamps, which stay strings: a
written date is an EDTF string to Lifehug, never a ``datetime.date``.
"""

from __future__ import annotations

import re

__all__ = ["YamlSubsetError", "loads"]


class YamlSubsetError(ValueError):
    """The text uses YAML this reader does not support, or is malformed."""


_NULLS = {"", "~", "null", "Null", "NULL"}
_TRUE = {"yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON"}
_FALSE = {"no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF"}
_INT_RE = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_FLOAT_RE = re.compile(r"^[-+]?([0-9][0-9_]*)?\.[0-9_]*([eE][-+][0-9]+)?$")
_KEY_RE = re.compile(r"^([^\s'\"\[\]{},#&*!|>%@`-][^:#]*?|-[^\s:][^:#]*?)\s*:(?:\s|$)")
_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
    "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
    "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}

# PyYAML's 1.1 resolver also treats these as floats; the letters YAML never
# writes them, but resolving them the same way keeps the parity test honest.
_SPECIAL_FLOATS = {
    ".inf": float("inf"), ".Inf": float("inf"), ".INF": float("inf"),
    "+.inf": float("inf"), "+.Inf": float("inf"), "+.INF": float("inf"),
    "-.inf": float("-inf"), "-.Inf": float("-inf"), "-.INF": float("-inf"),
}


def _resolve_plain(text: str) -> object:
    if text in _NULLS:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if _INT_RE.match(text):
        return int(text.replace("_", ""))
    if text in _SPECIAL_FLOATS:
        return _SPECIAL_FLOATS[text]
    if _FLOAT_RE.match(text) and any(ch.isdigit() for ch in text):
        return float(text.replace("_", ""))
    return text


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _strip_comment(text: str) -> str:
    """Drop a trailing `` # comment`` from a plain scalar fragment."""
    match = re.search(r"(^|\s)#", text)
    return text[: match.start()] if match else text


def _fold(lines: list[str], *, quoted: bool = False) -> str:
    """YAML line folding for a multi-line flow scalar body (quotes removed).

    A single line break becomes a space; each EMPTY line between two lines
    becomes a newline; leading white space on continuation lines and trailing
    white space before a break are dropped. The LAST line of a quoted scalar
    keeps its trailing white space (it ends at the quote, not at a break) and
    is joined even when it holds nothing but the closing quote."""
    out = lines[0].rstrip(" \t")
    pending = 0
    for index, line in enumerate(lines[1:], start=1):
        last = index == len(lines) - 1
        if quoted and last:
            piece = line.lstrip(" \t")
        else:
            piece = line.strip(" \t")
            if not piece:
                pending += 1
                continue
        out += ("\n" * pending) if pending else " "
        pending = 0
        out += piece
    if pending:
        out += "\n" * pending
    return out


def _unescape_double(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            raise YamlSubsetError("dangling backslash in a double-quoted scalar")
        code = raw[i]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            i += 1
        elif code in _HEX_ESCAPES:
            width = _HEX_ESCAPES[code]
            digits = raw[i + 1: i + 1 + width]
            if len(digits) != width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                raise YamlSubsetError(f"bad \\{code} escape")
            out.append(chr(int(digits, 16)))
            i += 1 + width
        else:
            raise YamlSubsetError(f"unknown escape \\{code}")
    return "".join(out)


def _fold_double_lines(lines: list[str]) -> str:
    out = ""
    pending = 0
    escape_next_break = False
    for index, line in enumerate(lines):
        last = index == len(lines) - 1
        piece = line if index == 0 else line.lstrip(" \t")
        if index:
            if escape_next_break:
                pass  # joined with no separator
            elif not piece.strip(" \t") and not last:
                pending += 1
                continue
            else:
                out += ("\n" * pending) if pending else " "
            pending = 0
        if not last:
            backslashes = len(piece) - len(piece.rstrip("\\"))
            if backslashes % 2 == 1:
                escape_next_break = True
                piece = piece[:-1]
            else:
                escape_next_break = False
                stripped = piece.rstrip(" \t")
                tail = len(stripped) - len(stripped.rstrip("\\"))
                if tail % 2 == 1 and len(stripped) < len(piece):
                    stripped = piece[: len(stripped) + 1]  # keep an escaped space
                piece = stripped
        out += piece
    return _unescape_double(out)


def _closing_quote(text: str, quote: str, start: int = 1) -> int:
    """Index of the quote that closes a scalar opened at ``text[start - 1]``,
    or -1. ``''`` inside single quotes and ``\\"`` inside double quotes do
    not close it."""
    k = start
    while True:
        k = text.find(quote, k)
        if k == -1:
            return -1
        if quote == "'":
            if text[k + 1: k + 2] == "'":
                k += 2
                continue
            return k
        backslashes = len(text[start:k]) - len(text[start:k].rstrip("\\"))
        if backslashes % 2 == 0:
            return k
        k += 1


class _Parser:
    def __init__(self, text: str):
        for line in text.split("\n"):
            if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
                # Tabs are never indentation in YAML; refuse rather than guess.
                raise YamlSubsetError("tab used for indentation")
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0

    # ── helpers ──────────────────────────────────────────────────────────
    def _skip_blank(self) -> None:
        while self.i < len(self.lines) and _is_blank_or_comment(self.lines[self.i]):
            self.i += 1

    def _peek(self) -> str | None:
        self._skip_blank()
        return self.lines[self.i] if self.i < len(self.lines) else None

    # ── entry ────────────────────────────────────────────────────────────
    def parse_document(self) -> object:
        line = self._peek()
        if line is None:
            return None
        if line.startswith("---") or line.startswith("..."):
            raise YamlSubsetError("document markers are not supported")
        value = self.parse_node(_indent(line))
        if self._peek() is not None:
            raise YamlSubsetError(f"unexpected content at line {self.i + 1}")
        return value

    def parse_node(self, indent: int) -> object:
        line = self._peek()
        if line is None:
            return None
        content = line[indent:]
        if content == "-" or content.startswith("- "):
            return self.parse_sequence(indent)
        if _KEY_RE.match(content) or content.startswith(('"', "'")) and self._quoted_key(content):
            return self.parse_mapping(indent)
        # A bare scalar or flow collection as a whole node.
        self.i += 1
        return self.parse_inline(content, indent - 1)

    @staticmethod
    def _quoted_key(content: str) -> bool:
        end = _closing_quote(content, content[0])
        return end != -1 and re.match(r"\s*:(\s|$)", content[end + 1:]) is not None

    def parse_sequence(self, indent: int) -> list:
        items: list = []
        while True:
            line = self._peek()
            if line is None or _indent(line) != indent:
                break
            content = line[indent:]
            if not (content == "-" or content.startswith("- ")):
                break
            rest = content[1:].lstrip(" ")
            if not rest or rest.startswith("#"):
                self.i += 1
                nxt = self._peek()
                if nxt is not None and _indent(nxt) > indent:
                    items.append(self.parse_node(_indent(nxt)))
                else:
                    items.append(None)
                continue
            child_indent = indent + (len(content) - len(rest))
            if rest.startswith("- ") or _KEY_RE.match(rest) or (
                rest.startswith(('"', "'")) and self._quoted_key(rest)
            ):
                # Re-indent the item's first line so it reads as a node.
                self.lines[self.i] = " " * child_indent + rest
                items.append(self.parse_node(child_indent))
                continue
            self.i += 1
            items.append(self.parse_inline(rest, indent))
        return items

    def parse_mapping(self, indent: int) -> dict:
        mapping: dict = {}
        while True:
            line = self._peek()
            if line is None or _indent(line) != indent:
                break
            content = line[indent:]
            if content == "-" or content.startswith("- "):
                break
            key, rest = self._split_key(content)
            if key in mapping:
                raise YamlSubsetError(f"duplicate key {key!r} at line {self.i + 1}")
            rest = rest.strip(" ")
            self.i += 1
            if not rest or rest.startswith("#"):
                nxt = self._peek()
                if nxt is not None and _indent(nxt) > indent:
                    mapping[key] = self.parse_node(_indent(nxt))
                elif nxt is not None and _indent(nxt) == indent and (
                    nxt[indent:] == "-" or nxt[indent:].startswith("- ")
                ):
                    mapping[key] = self.parse_sequence(indent)  # indentless sequence
                else:
                    mapping[key] = None
                continue
            mapping[key] = self.parse_inline(rest, indent)
        return mapping

    def _split_key(self, content: str) -> tuple[str, str]:
        if content.startswith(('"', "'")):
            quote = content[0]
            end = _closing_quote(content, quote)
            raw = content[1:end]
            key = raw.replace("''", "'") if quote == "'" else _unescape_double(raw)
            after = content[end + 1:]
            colon = after.index(":")
            return key, after[colon + 1:]
        match = _KEY_RE.match(content)
        if not match:
            raise YamlSubsetError(f"expected 'key: value' at line {self.i + 1}")
        key = match.group(1).strip()
        if key.startswith("? "):
            raise YamlSubsetError("complex keys are not supported")
        return key, content[match.end():]

    # ── inline values (possibly continued on following lines) ─────────────
    def _continuation(self, parent_indent: int) -> list[str]:
        """Following lines that continue a scalar: more indented than the
        parent, or blank (a blank line inside a folded scalar is a newline)."""
        out: list[str] = []
        j = self.i
        while j < len(self.lines):
            line = self.lines[j]
            if not line.strip():
                out.append("")
                j += 1
                continue
            if _indent(line) <= parent_indent:
                break
            out.append(line)
            j += 1
        while out and out[-1] == "":
            out.pop()
        self.i += len(out)
        return out

    def parse_inline(self, text: str, parent_indent: int) -> object:
        text = text.lstrip(" ")
        if not text:
            return None
        head = text[0]
        if head in "&*!":
            raise YamlSubsetError("anchors, aliases and tags are not supported")
        if head in "|>":
            raise YamlSubsetError("block scalars are not supported")
        if head == "'":
            return self._single(text, parent_indent)
        if head == '"':
            return self._double(text, parent_indent)
        if head in "[{":
            return self._flow(text, parent_indent)
        first = _strip_comment(text).rstrip(" ")
        lines = [first]
        if first == text.rstrip(" "):  # no comment ended it: may continue
            for extra in self._continuation(parent_indent):
                if extra and extra.lstrip().startswith("#"):
                    break
                lines.append(_strip_comment(extra) if extra else extra)
        value = _fold(lines) if len(lines) > 1 else first
        if len(lines) == 1:
            return _resolve_plain(value)
        return value

    def _gather_quoted(self, text: str, parent_indent: int, quote: str) -> tuple[list[str], str]:
        """The lines of a quoted scalar from its opening quote to its closing
        one, and whatever follows the closing quote on its line."""
        lines = [text[1:]]

        while True:
            end = _closing_quote(lines[-1], quote, 0)
            if end != -1:
                tail = lines[-1][end + 1:]
                lines[-1] = lines[-1][:end]
                return lines, tail
            if self.i >= len(self.lines):
                raise YamlSubsetError("unterminated quoted scalar")
            lines.append(self.lines[self.i])
            self.i += 1

    def _check_tail(self, tail: str) -> None:
        tail = tail.strip(" ")
        if tail and not tail.startswith("#"):
            raise YamlSubsetError(f"unexpected text after a quoted scalar: {tail!r}")

    def _single(self, text: str, parent_indent: int) -> str:
        lines, tail = self._gather_quoted(text, parent_indent, "'")
        self._check_tail(tail)
        value = _fold(lines, quoted=True) if len(lines) > 1 else lines[0]
        return value.replace("''", "'")

    def _double(self, text: str, parent_indent: int) -> str:
        lines, tail = self._gather_quoted(text, parent_indent, '"')
        self._check_tail(tail)
        return _fold_double_lines(lines)

    def _flow(self, text: str, parent_indent: int) -> object:
        buffer = text
        while True:
            try:
                value, end = _FlowReader(buffer).read()
            except _NeedMore:
                if self.i >= len(self.lines):
                    raise YamlSubsetError("unterminated flow collection") from None
                buffer += "\n" + self.lines[self.i]
                self.i += 1
                continue
            self._check_tail(buffer[end:].split("\n", 1)[0] if "\n" not in buffer[end:] else buffer[end:])
            return value


class _NeedMore(Exception):
    pass


class _FlowReader:
    def __init__(self, text: str):
        self.s = text
        self.k = 0

    def _ws(self) -> None:
        while self.k < len(self.s):
            ch = self.s[self.k]
            if ch in " \t\n":
                self.k += 1
            elif ch == "#" and (self.k == 0 or self.s[self.k - 1] in " \t\n"):
                nl = self.s.find("\n", self.k)
                if nl == -1:
                    self.k = len(self.s)
                else:
                    self.k = nl
            else:
                break
        if self.k >= len(self.s):
            raise _NeedMore

    def read(self) -> tuple[object, int]:
        value = self._value()
        return value, self.k

    def _value(self) -> object:
        self._ws()
        ch = self.s[self.k]
        if ch == "[":
            return self._seq()
        if ch == "{":
            return self._map()
        if ch == "'":
            return self._single()
        if ch == '"':
            return self._double()
        if ch in "&*!|>":
            raise YamlSubsetError("anchors, aliases, tags and block scalars are not supported")
        return self._plain()

    def _seq(self) -> list:
        self.k += 1
        out: list = []
        while True:
            self._ws()
            if self.s[self.k] == "]":
                self.k += 1
                return out
            out.append(self._value())
            self._ws()
            ch = self.s[self.k]
            if ch == ",":
                self.k += 1
            elif ch != "]":
                raise YamlSubsetError(f"expected ',' or ']' in a flow sequence, got {ch!r}")

    def _map(self) -> dict:
        self.k += 1
        out: dict = {}
        while True:
            self._ws()
            if self.s[self.k] == "}":
                self.k += 1
                return out
            key = self._value()
            self._ws()
            if self.s[self.k] != ":":
                raise YamlSubsetError("expected ':' in a flow mapping")
            self.k += 1
            value = self._value()
            if isinstance(key, (list, dict)):
                raise YamlSubsetError("complex keys are not supported")
            out[key] = value
            self._ws()
            ch = self.s[self.k]
            if ch == ",":
                self.k += 1
            elif ch != "}":
                raise YamlSubsetError(f"expected ',' or '}}' in a flow mapping, got {ch!r}")

    def _single(self) -> str:
        start = self.k + 1
        k = start
        while True:
            k = self.s.find("'", k)
            if k == -1:
                raise _NeedMore
            if self.s[k + 1: k + 2] == "'":
                k += 2
                continue
            break
        raw = self.s[start:k]
        self.k = k + 1
        lines = raw.split("\n")
        value = _fold(lines, quoted=True) if len(lines) > 1 else raw
        return value.replace("''", "'")

    def _double(self) -> str:
        start = self.k + 1
        k = start
        while True:
            k = self.s.find('"', k)
            if k == -1:
                raise _NeedMore
            backslashes = len(self.s[start:k]) - len(self.s[start:k].rstrip("\\"))
            if backslashes % 2 == 0:
                break
            k += 1
        raw = self.s[start:k]
        self.k = k + 1
        return _fold_double_lines(raw.split("\n"))

    def _plain(self) -> object:
        start = self.k
        while self.k < len(self.s):
            ch = self.s[self.k]
            if ch in ",[]{}":
                break
            if ch == ":" and (self.k + 1 >= len(self.s) or self.s[self.k + 1] in " \t\n,[]{}"):
                break
            if ch == "#" and self.k > start and self.s[self.k - 1] in " \t":
                break
            self.k += 1
        if self.k >= len(self.s):
            raise _NeedMore
        raw = self.s[start:self.k]
        lines = raw.split("\n")
        text = _fold(lines).strip(" \t") if len(lines) > 1 else raw.strip(" \t")
        return _resolve_plain(text) if len(lines) == 1 else text


def loads(text: str) -> object:
    """Parse one YAML document in the supported subset."""
    return _Parser(text).parse_document()
