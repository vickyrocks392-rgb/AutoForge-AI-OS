"""A real COBOL intermediate representation for Phase 20 transformation.

This is *not* a keyword scanner. It produces a typed IR with:

* a **data dictionary** whose field offsets and byte sizes are computed from
  PIC/USAGE the way a COBOL compiler computes them (display numerics, COMP-3
  packed decimal, COMP/BINARY, implied decimal points, OCCURS, REDEFINES,
  88-level condition names);
* a **record layout** per 01-level group so a transpiler can address bytes
  exactly the way the original program does;
* a **statement AST** for the PROCEDURE DIVISION verbs the modernization
  scope supports.

Anything outside the supported subset is recorded as a
:class:`UnsupportedConstruct` with its source line. The caller must treat a
non-empty gap list as a hard stop: an unmigrated verb is a certification
failure, never a silently dropped line.

Byte-exactness matters more than elegance here. A COBOL record is a byte
buffer, and behavioural equivalence with the legacy system is a byte-for-byte
comparison of output files. So the IR models records as flat byte ranges
rather than as objects with accessors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "FieldDef",
    "RecordLayout",
    "UnsupportedConstruct",
    "DataDictionary",
    "COBOLProgram",
    "parse_picture",
    "parse_data_entries",
    "build_layout",
    "is_name_part",
    "join_qualified",
]


# ── Qualified data names ─────────────────────────────────────────────────────
#
# A COBOL operand is a *qualified data name*: ``FIELD OF RECORD``, and any level
# of that chain may itself carry a subscript or reference modification
# (``TABLE-ITEM(3) OF GROUP-A OF RECORD-Z``). Any component that splits an
# operand list on whitespace therefore has to put the chain back together, or
# ``OF`` becomes an operand in its own right and the real field is lost.
#
# These two helpers are that boundary. They are deliberately conservative: only
# a word-delimited ``OF`` standing between two *identifier-shaped* levels is
# treated as qualification, so ``OF`` keeps its ordinary meaning everywhere
# else (prose such as ``AT END OF PAGE``, or a quoted literal).

#: One level of a qualified data name, optionally subscripted / reference
#: modified. A level must begin with a letter, so numeric literals (``20250101``)
#: and quoted literals (``"DEPO"``) can never be mistaken for one.
_NAME_PART_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*(?:\([^()]*\))?$")


def is_name_part(token: str) -> bool:
    """True when ``token`` can be one level of a qualified data name."""
    return bool(_NAME_PART_RE.match(token.strip()))


def join_qualified(tokens: list[str]) -> list[str]:
    """Re-join ``A OF B`` groups produced by splitting an operand list.

    ``A OF B`` becomes one operand; ``A OF B OF C`` chains correctly; anything
    that is not a genuine qualification is returned untouched, so a lone ``OF``
    in prose keeps whatever meaning it had before.
    """
    joined: list[str] = []
    index = 0
    while index < len(tokens):
        parts = [tokens[index]]
        cursor = index + 1
        # A chain continues while `OF` sits between two identifier-shaped levels.
        while (
            cursor + 1 < len(tokens)
            and tokens[cursor].strip().upper() == "OF"
            and is_name_part(parts[-1])
            and is_name_part(tokens[cursor + 1])
        ):
            parts.append(tokens[cursor])
            parts.append(tokens[cursor + 1])
            cursor += 2
        joined.append(" ".join(parts))
        index = cursor
    return joined

# ── PIC parsing ─────────────────────────────────────────────────────────────

_PIC_RE = re.compile(
    r"^(?P<sign>S)?(?P<int>(?:9\(?\d*\)?)+)(?P<v>V(?:9(?:\(\d+\))?)?)?(?P<frac>(?:9(?:\(\d+\))?)*)$"
)

_PIC_RE_SIMPLE = re.compile(r"^(?P<sign>S)?(?P<digits>9+)(?P<v>V)?(?P<frac>9*)$")


@dataclass(frozen=True)
class Picture:
    """A parsed COBOL PICTURE clause."""

    raw: str
    category: str  # "alphanumeric" | "numeric"
    signed: bool
    digits: int  # total digit positions (integer + fractional)
    scale: int  # implied decimal places
    char_count: int  # alphanumeric character count

    @property
    def is_numeric(self) -> bool:
        return self.category == "numeric"


def _expand_repeat(token: str) -> str:
    """``9(11)`` -> ``99999999999``; ``99`` stays ``99``."""
    match = re.fullmatch(r"([X9A])(?:\((\d+)\))?", token)
    if not match:
        return token
    symbol, repeat = match.group(1), match.group(2)
    return symbol * (int(repeat) if repeat else 1)


def parse_picture(pic: str) -> Picture:
    """Parse a PICTURE string into counts.

    Supports the shapes the certified workloads actually use: ``X``, ``X(n)``,
    ``9``, ``9(n)``, ``S9(n)``, ``S9(n)V99``, ``S9(n)V9(n)`` and ``A(n)``.
    Anything else raises, because guessing a layout would silently corrupt
    every record downstream.
    """
    raw = pic.strip().rstrip(".")
    if not raw:
        raise ValueError("empty PICTURE clause")

    upper = raw.upper().replace(" ", "")

    # Alphanumeric forms: X, X(n), XX, XXXX, A(n) ...
    if re.fullmatch(r"[XA]+|[XA]\(\d+\)|[XA]+(?:\(\d+\))?[XA]+", upper):
        char_count = 0
        index = 0
        while index < len(upper):
            char = upper[index]
            if index + 1 < len(upper) and upper[index + 1] == "(":
                close = upper.find(")", index + 1)
                if close == -1:
                    raise ValueError(f"unsupported PICTURE {pic!r}")
                count_text = upper[index + 2:close]
                if not count_text.isdigit():
                    raise ValueError(f"unsupported PICTURE {pic!r}")
                char_count += int(count_text)
                index = close + 1
                continue
            char_count += 1
            index += 1
        return Picture(
            raw=raw, category="alphanumeric", signed=False, digits=0, scale=0,
            char_count=char_count,
        )

    if not upper.startswith(("9", "S9")):
        raise ValueError(f"unsupported PICTURE {pic!r}")

    signed = upper.startswith("S")
    body = upper[1:] if signed else upper

    match = re.fullmatch(r"(\d+|\d+\(\d+\)|\(\d+\))V(\d+|\d*\(\d+\)|\d+\(\d+\))?", body)
    if not match:
        # No decimal point: a plain run of 9s, possibly with repeats.
        expanded = _expand_numeric_run(body)
        if expanded is None:
            raise ValueError(f"unsupported PICTURE {pic!r}")
        return Picture(
            raw=raw, category="numeric", signed=signed, digits=len(expanded),
            scale=0, char_count=0,
        )

    int_part = _expand_numeric_run(match.group(1))
    frac_part = _expand_numeric_run(match.group(2) or "9")
    if int_part is None or frac_part is None:
        raise ValueError(f"unsupported PICTURE {pic!r}")
    return Picture(
        raw=raw, category="numeric", signed=signed,
        digits=len(int_part) + len(frac_part), scale=len(frac_part), char_count=0,
    )


def _expand_numeric_run(token: str) -> str | None:
    """Expand a numeric PIC run such as ``9(10)V99`` into literal digits.

    ``9`` and ``9(n)`` are both repeat specifications, so ``9(8)`` yields
    eight digits -- not one digit followed by eight more.
    """
    if not token:
        return None
    out: list[str] = []
    index = 0
    while index < len(token):
        char = token[index]
        if char == "9":
            index += 1
            # An immediately following "(n)" is the repeat count for this 9.
            if index < len(token) and token[index] == "(":
                close = token.find(")", index)
                if close == -1:
                    return None
                count_text = token[index + 1:close]
                if not count_text.isdigit():
                    return None
                out.append("9" * int(count_text))
                index = close + 1
            else:
                out.append("9")
            continue
        if char == "(":
            close = token.find(")", index)
            if close == -1:
                return None
            count_text = token[index + 1:close]
            if not count_text.isdigit():
                return None
            out.append("9" * int(count_text))
            index = close + 1
            continue
        if char.isdigit():
            out.append(char)
            index += 1
            continue
        return None
    return "".join(out)


@dataclass
class UnsupportedConstruct:
    """A COBOL construct the modernization scope does not cover.

    Presence of any of these is a hard stop. The pipeline refuses to declare a
    project validated while an unmigrated verb remains.
    """

    construct: str
    line: int
    text: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "construct": self.construct,
            "line": self.line,
            "text": self.text,
            "reason": self.reason,
        }


@dataclass
class FieldDef:
    """One data description entry with its resolved byte layout."""

    name: str  # "" for FILLER
    level: int
    picture: Picture | None
    usage: str  # DISPLAY | COMP-3 | COMP-5 | BINARY
    offset: int = 0
    size: int = 0
    occurs: int = 1
    redefines: str | None = None
    value: str | None = None
    parent: str | None = None
    conditions: dict[str, str] = field(default_factory=dict)
    source_line: int = 0
    is_group: bool = False
    children: list[int] = field(default_factory=list)
    #: For OCCURS fields: byte offset of the current repetition.
    index: int = 0

    @property
    def category(self) -> str:
        if self.picture is None:
            return "group"
        return self.picture.category

    @property
    def signed(self) -> bool:
        return bool(self.picture and self.picture.signed)

    @property
    def digits(self) -> int:
        return self.picture.digits if self.picture else 0

    @property
    def scale(self) -> int:
        return self.picture.scale if self.picture else 0

    @property
    def qualified(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name


@dataclass
class RecordLayout:
    """The byte layout of one 01-level record, plus its data dictionary."""

    record_name: str
    size: int
    fields: list[FieldDef]
    #: Field name (upper) -> index into ``fields`` for leaves.
    index: dict[str, int]
    #: 88-level condition name -> "OWNER=VALUE" for code generation.
    conditions: dict[str, str] = field(default_factory=dict)

    def leaf(self, name: str) -> FieldDef | None:
        key = name.strip().upper()
        idx = self.index.get(key)
        return self.fields[idx] if idx is not None else None

    def total_size(self) -> int:
        return self.size

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_name": self.record_name,
            "size": self.size,
            "fields": [
                {
                    "name": f.qualified,
                    "level": f.level,
                    "offset": f.offset,
                    "size": f.size,
                    "occurs": f.occurs,
                    "usage": f.usage,
                    "category": f.category,
                    "digits": f.digits,
                    "scale": f.scale,
                    "signed": f.signed,
                    "picture": f.picture.raw if f.picture else None,
                    "conditions": dict(f.conditions),
                }
                for f in self.fields
                if not f.name or f.name != "FILLER"
            ],
        }


# ── Source normalization ────────────────────────────────────────────────────

def looks_fixed_format(text: str) -> bool:
    """Heuristic: fixed-format sources put a marker in column 7.

    Free-format sources never indent a literal ``*`` into column 7, while
    fixed-format CardDemo sources use column 7 for the indicator area.
    """
    for line in text.splitlines()[:120]:
        if len(line) >= 7 and line[6] in ("*", "/"):
            return True
        if len(line) >= 7 and line[6] == "-" and line[:6].strip().isdigit():
            return True
    return False


def source_lines(text: str, *, source_format: str | None = None) -> list[tuple[int, str]]:
    """Return ``(line_number, code)`` pairs with comments/continuations resolved.

    Both COBOL source references are supported: fixed (columns 8-72, column 7
    indicator) and free. Indicator ``*``/``/`` comment lines and ``D`` debug
    lines are dropped; ``-`` continuation lines are joined onto the previous
    line so multi-line statements and PIC clauses parse as one unit.
    """
    fmt = source_format or ("fixed" if looks_fixed_format(text) else "free")
    out: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if fmt == "fixed":
            indicator = raw[6] if len(raw) > 6 else " "
            code = raw[7:72] if len(raw) > 7 else ""
        else:
            indicator = " "
            stripped = raw.strip()
            # Free-format comment lines begin with '*' or '*>'.
            if stripped.startswith("*"):
                continue
            code = raw
        if indicator in ("*", "/", "D"):
            continue
        code = code.rstrip()
        if not code.strip():
            continue
        if indicator == "-" and out:
            prev_number, prev_code = out[-1]
            out[-1] = (prev_number, f"{prev_code} {code.strip()}")
            continue
        out.append((number, code))
    return out

_ENTRY_HEAD_RE = re.compile(
    r"^(?P<level>\d{1,2})\s+(?P<name>[A-Za-z0-9][A-Za-z0-9\-_]*)\b(?P<rest>.*)$"
)

_PIC_RE = re.compile(
    r"\bPIC(?:TURE)?\s+(?:IS\s+)?(?P<pic>[A-Za-z0-9()VXS9.\-]+)", re.IGNORECASE
)
_USAGE_RE = re.compile(
    r"\bUSAGE\s+(?:IS\s+)?(?P<usage>[A-Za-z0-9\-]+)|"
    r"\b(?P<usage_bare>COMP-3|PACKED-DECIMAL|COMP-5|COMP-4|COMP-2|COMP-1|COMP|BINARY)\b",
    re.IGNORECASE,
)
_OCCURS_RE = re.compile(r"\bOCCURS\s+(?:(\d+)|(\d+)\s+TO\s+(\d+))", re.IGNORECASE)
_REDEFINES_RE = re.compile(r"\bREDEFINES\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.IGNORECASE)
_VALUE_RE = re.compile(r"\bVALUE\s+(?:IS\s+)?(?P<value>\S+)", re.IGNORECASE)
_CONDITION_RE = re.compile(
    r"^88\s+(?P<name>[A-Za-z0-9][A-Za-z0-9\-_]*)\s+"
    r"(?:VALUE\s+(?:IS\s+)?)?(?P<value>.+)$",
    re.IGNORECASE,
)


@dataclass
class DataEntry:
    """A raw, unresolved data description entry."""

    level: int
    name: str
    line: int
    picture: str | None = None
    usage: str = "DISPLAY"
    occurs: int = 1
    redefines: str | None = None
    value: str | None = None
    sign_mode: str | None = None


def _normalize_usage(token: str) -> str:
    token = (token or "").strip().upper()
    if token in {"COMP-3", "PACKED-DECIMAL"}:
        return "COMP-3"
    if token in {"COMP", "COMPUTATIONAL"}:
        return "COMP"
    if token in {"COMP-5", "COMP-4", "BINARY"}:
        return "BINARY"
    if token in {"COMP-1", "COMP-2"}:
        return "FLOAT"
    return "DISPLAY"


def parse_data_entries(
    lines: Iterable[tuple[int, str]],
) -> tuple[list[DataEntry], list[UnsupportedConstruct]]:
    """Parse DATA DIVISION lines into ordered, unresolved entries.

    Clause extraction is done by searching the entry tail for each clause rather
    than by one monolithic pattern, so a real-world entry such as
    ``05 CURR-BAL PIC S9(11)V99 COMP-3.`` and a bare group entry such as
    ``01 ACCOUNT-RECORD.`` are both handled without guessing.
    """
    entries: list[DataEntry] = []
    gaps: list[UnsupportedConstruct] = []
    #: Tails of entries still accepting clauses (fixed-format clause wrapping).
    open_rest: str | None = None
    last_entry: DataEntry | None = None

    for number, code in lines:
        text = _strip_inline_comment(code.strip())

        if re.match(r"^88\s", text):
            open_rest, last_entry = None, None
            cond = _CONDITION_RE.match(text)
            if cond:
                entries.append(
                    DataEntry(
                        level=88,
                        name=cond.group("name").upper(),
                        line=number,
                        value=strip_trailing_period(cond.group("value")),
                    )
                )
            else:
                gaps.append(
                    UnsupportedConstruct(
                        construct="condition", line=number, text=text,
                        reason="88-level clause is not in the supported form",
                    )
                )
            continue

        head = _ENTRY_HEAD_RE.match(text)
        if not head:
            # A clause may wrap onto its own line in fixed-format source, e.g.
            # ``05 F PIC S9(10)V99`` followed by ``   USAGE IS COMP-3.``.
            if (
                last_entry is not None
                and open_rest is not None
                and re.match(r"^(PIC|PICTURE|USAGE|VALUE|OCCURS|REDEFINES|SIGN)\b", text, re.I)
            ):
                open_rest = f"{open_rest} {text}"
                rest = open_rest
                if _PIC_RE.search(rest) and last_entry.picture is None:
                    last_entry.picture = _PIC_RE.search(rest).group("pic").rstrip(".")
                usage_match = _USAGE_RE.search(rest)
                if usage_match:
                    token = usage_match.group("usage") or usage_match.group("usage_bare")
                    last_entry.usage = _normalize_usage(token or "")
                value_match = _VALUE_RE.search(rest)
                if value_match:
                    last_entry.value = strip_trailing_period(value_match.group("value"))
                continue
            continue

        rest = head.group("rest") or ""
        level = int(head.group("level"))
        name = head.group("name").upper()

        pic_match = _PIC_RE.search(rest)
        picture = pic_match.group("pic").rstrip(".") if pic_match else None

        usage_match = _USAGE_RE.search(rest)
        usage_token = ""
        if usage_match:
            usage_token = usage_match.group("usage") or usage_match.group("usage_bare") or ""
        usage = _normalize_usage(usage_token)

        occurs = 1
        occurs_match = _OCCURS_RE.search(rest)
        if occurs_match:
            if occurs_match.group(3):
                gaps.append(
                    UnsupportedConstruct(
                        construct="occurs-to", line=number, text=text,
                        reason="OCCURS n TO m is not supported in the certified scope",
                    )
                )
            elif occurs_match.group(1):
                occurs = int(occurs_match.group(1))

        redefines_match = _REDEFINES_RE.search(rest)
        value_match = _VALUE_RE.search(rest)

        last_entry = DataEntry(
            level=level,
            name=name,
            line=number,
            picture=picture,
            usage=usage,
            occurs=occurs,
            redefines=(redefines_match.group(1).upper() if redefines_match else None),
            value=(
                strip_trailing_period(value_match.group("value"))
                if value_match else None
            ),
        )
        open_rest = rest
        entries.append(last_entry)
    return entries, gaps

# ── Layout construction ─────────────────────────────────────────────────────

_BINARY_BYTES = (
    (2, 2), (4, 2), (9, 4), (18, 8),
)


def _binary_size(digits: int) -> int:
    for limit, size in _BINARY_BYTES:
        if digits <= limit:
            return size
    return 8


def element_size(picture: Picture, usage: str) -> int:
    """Bytes occupied by one element of a PIC/USAGE pair."""
    if picture.is_numeric:
        if usage == "COMP-3":
            # Packed decimal: one nibble per digit plus a sign nibble.
            return (picture.digits // 2) + 1
        if usage == "BINARY":
            return _binary_size(picture.digits)
        if usage == "FLOAT":
            return 8
        return picture.digits  # DISPLAY, sign embedded in the trailing digit
    return picture.char_count


@dataclass
class _Node:
    entry: DataEntry
    children: list["_Node"] = field(default_factory=list)
    size: int = 0
    offset: int = 0


def build_record_layout(
    entries: list[DataEntry],
    *,
    record_name: str,
    conditions: dict[str, str] | None = None,
    gaps: list[UnsupportedConstruct] | None = None,
) -> RecordLayout:
    """Resolve a flat entry list into a byte layout for one 01-level record.

    Handles nested groups, OCCURS repetition, REDEFINES overlay and 88-level
    condition names. Anything it cannot resolve is appended to ``gaps`` rather
    than guessed, so the caller can fail closed.
    """
    gaps = gaps if gaps is not None else []
    conditions = conditions or {}

    # 88-level entries belong to the nearest preceding non-88 entry. Resolve
    # ownership BEFORE filtering them out, otherwise the association is lost.
    conditions: dict[str, str] = dict(conditions or {})
    condition_owner: dict[str, str] = {}
    owner_stack: list[str] = []
    plain_entries: list[DataEntry] = []
    for entry in entries:
        if entry.level == 88:
            if owner_stack:
                condition_owner[entry.name] = owner_stack[-1]
            continue
        plain_entries.append(entry)
        owner_stack.append(entry.name)
    entries = plain_entries

    # Build the group tree from the level numbers.
    roots: list[_Node] = []
    stack: list[_Node] = []
    for entry in entries:
        node = _Node(entry=entry)
        while stack and stack[-1].entry.level >= entry.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    resolved: list[FieldDef] = []
    index: dict[str, int] = {}
    conditions_index: dict[str, str] = {}

    def resolve(node: _Node, base: int, parent_name: str | None) -> int:
        entry = node.entry
        # Size first (children depend on it), then offset.
        if entry.picture:
            try:
                picture = parse_picture(entry.picture)
            except ValueError as exc:
                gaps.append(
                    UnsupportedConstruct(
                        construct="picture", line=entry.line,
                        text=f"PIC {entry.picture}", reason=str(exc),
                    )
                )
                picture = Picture(
                    raw=entry.picture or "", category="alphanumeric", signed=False,
                    digits=0, scale=0, char_count=0,
                )
        else:
            picture = None

        offset = node.offset if entry.redefines else base

        if picture is not None:
            unit = element_size(picture, entry.usage)
            node.size = unit * max(1, entry.occurs)
            is_group = False
        else:
            # A group: size is the sum of its children, repeated OCCURS times.
            child_size = 0
            cursor = offset
            for child in node.children:
                child_size += resolve(child, cursor, entry.name)
                # ``child.size`` already includes the child's OCCURS count.
                cursor = child.offset + child.size
            node.size = child_size * max(1, entry.occurs)
            is_group = True

        node.offset = offset

        fdef = FieldDef(
            name=entry.name,
            level=entry.level,
            picture=picture,
            usage=entry.usage,
            offset=offset,
            size=node.size,
            occurs=max(1, entry.occurs),
            redefines=entry.redefines,
            value=entry.value,
            parent=parent_name,
            source_line=entry.line,
            is_group=is_group,
        )
        condition_values = {
            cond_name: cond_value
            for cond_name, cond_value in conditions.items()
            if condition_owner.get(cond_name) == entry.name
        }
        fdef.conditions.update(condition_values)
        position = len(resolved)
        resolved.append(fdef)
        if entry.name and entry.name != "FILLER" and picture is not None:
            key = entry.name
            if key not in index:
                index[key] = position
        for cond_name in condition_values:
            conditions_index[cond_name] = entry.name
        return node.size

    cursor = 0
    for root in roots:
        cursor += resolve(root, cursor, None)

    total = max((f.offset + f.size for f in resolved), default=0)
    layout = RecordLayout(
        record_name=record_name.upper(),
        size=total,
        fields=resolved,
        index=index,
    )
    # Record-level condition map so the code generator can test 88-level names.
    for fdef in resolved:
        for cond_name, cond_value in fdef.conditions.items():
            layout.conditions[cond_name] = f"{fdef.name}={cond_value}"
    return layout


def strip_trailing_period(text: str) -> str:
    return text.rstrip().rstrip(".").rstrip()


_INLINE_COMMENT_RE = re.compile(r"\*>.*$")


def _strip_inline_comment(text: str) -> str:
    """Remove a COBOL free-format inline comment (``*>`` to end of line)."""
    return _INLINE_COMMENT_RE.sub("", text).rstrip()


@dataclass
class DataDictionary:
    """All records discovered in a program's DATA DIVISION."""

    records: dict[str, RecordLayout] = field(default_factory=dict)
    conditions: dict[str, str] = field(default_factory=dict)
    gaps: list[UnsupportedConstruct] = field(default_factory=list)

    def record(self, name: str) -> RecordLayout | None:
        return self.records.get(name.strip().upper())
