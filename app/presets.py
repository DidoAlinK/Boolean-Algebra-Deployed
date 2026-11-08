"""Operator presets.

A preset says which symbols the parser understands and what every operator MEANS.
Meaning is stored as a truth table, so any operator (even a custom one) works
without writing new code:

    unary  operator: table = [f(0), f(1)]
    binary operator: table = [f(0,0), f(0,1), f(1,0), f(1,1)]

Users can send their own preset with a request; it is validated by the models below.
"""
from __future__ import annotations

from itertools import product
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Fixity = Literal["prefix", "postfix", "infix"]

MAX_OPERATORS = 64
MAX_SYMBOL_LEN = 8


def is_word(symbol: str) -> bool:
    """Word symbols (and, nor, implies...) are matched as whole letter runs."""
    return symbol.isascii() and symbol.isalpha()


def _is_associative(table: list[int]) -> bool:
    def f(a: int, b: int) -> int:
        return table[(a << 1) | b]

    return all(f(f(a, b), c) == f(a, f(b, c)) for a, b, c in product((0, 1), repeat=3))


class OperatorDef(BaseModel):
    name: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    fixity: Fixity
    symbols: list[str] = Field(min_length=1, max_length=16)
    precedence: int = Field(ge=1, le=99, description="Higher binds tighter")
    assoc: Literal["left", "right"] = "left"
    table: list[int]
    nary: bool = Field(default=False, description="Chains like a.b.c are drawn as ONE multi-input gate")
    shape: str = Field(default="box", max_length=16, description="Gate drawing hint for the frontend")

    @field_validator("symbols")
    @classmethod
    def _check_symbols(cls, symbols: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in symbols:
            sym = raw.strip()
            if not sym:
                raise ValueError("symbols cannot be empty")
            if len(sym) > MAX_SYMBOL_LEN:
                raise ValueError(f"symbol {sym!r} is longer than {MAX_SYMBOL_LEN} characters")
            if any(ch.isspace() for ch in sym) or "(" in sym or ")" in sym:
                raise ValueError(f"symbol {sym!r} cannot contain spaces or brackets")
            if any(ch.isdigit() for ch in sym):
                raise ValueError(f"symbol {sym!r} cannot contain digits (0 and 1 are constants)")
            has_letter = any(ch.isascii() and ch.isalpha() for ch in sym)
            if has_letter and not is_word(sym):
                raise ValueError(f"symbol {sym!r} mixes letters and punctuation")
            if is_word(sym) and len(sym) < 2:
                raise ValueError(f"symbol {sym!r} is a single letter, which is reserved for variables")
            sym = sym.lower() if is_word(sym) else sym
            if sym not in cleaned:
                cleaned.append(sym)
        return cleaned

    @field_validator("table")
    @classmethod
    def _check_table(cls, table: list[int]) -> list[int]:
        if any(v not in (0, 1) for v in table):
            raise ValueError("table may only contain 0 and 1")
        return table

    @model_validator(mode="after")
    def _check_shape(self) -> "OperatorDef":
        expected = 4 if self.fixity == "infix" else 2
        if len(self.table) != expected:
            raise ValueError(f"{self.fixity} operator {self.name!r} needs a table of {expected} values")
        if self.nary:
            if self.fixity != "infix":
                raise ValueError("only infix operators can be nary")
            if not _is_associative(self.table):
                raise ValueError(f"operator {self.name!r} is not associative, so it cannot be nary")
        return self


class PresetDef(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=200)
    operators: list[OperatorDef] = Field(min_length=1, max_length=MAX_OPERATORS)
    implicit: str | None = Field(
        default=None,
        description="Name of the infix operator used when two terms touch, e.g. 'AND' so that xy means x AND y",
    )

    @model_validator(mode="after")
    def _check_preset(self) -> "PresetDef":
        owner: dict[str, str] = {}
        for op in self.operators:
            for sym in op.symbols:
                if sym in owner:
                    raise ValueError(f"symbol {sym!r} is used by both {owner[sym]} and {op.name}")
                owner[sym] = op.name
        if self.implicit is not None:
            if not any(op.name == self.implicit and op.fixity == "infix" for op in self.operators):
                raise ValueError(f"implicit operator {self.implicit!r} is not an infix operator of this preset")
        return self


class CompiledPreset:
    """Lookup tables built once per request so the tokenizer and parser stay simple."""

    def __init__(self, preset: PresetDef) -> None:
        self.name = preset.name
        self.by_symbol: dict[str, OperatorDef] = {}
        self.word_ops: dict[str, OperatorDef] = {}
        for op in preset.operators:
            for sym in op.symbols:
                (self.word_ops if is_word(sym) else self.by_symbol)[sym] = op
        # longest first, so "~&" is tried before "~" and "<->" before "-"
        self.symbols_by_length = sorted(self.by_symbol, key=len, reverse=True)
        self.implicit_op: OperatorDef | None = None
        if preset.implicit is not None:
            self.implicit_op = next(
                op for op in preset.operators if op.name == preset.implicit and op.fixity == "infix"
            )


# ---------------------------------------------------------------------------
# Built-in presets. One master table, then each preset picks the "styles" it wants.
# ---------------------------------------------------------------------------
# (name, fixity, precedence, assoc, table, nary, shape, {style: symbols})
_MASTER = [
    ("NOT", "prefix", 60, "left", [1, 0], False, "not",
     {"text": ["!", "~"], "prog": ["!", "~"], "math": ["¬"], "word": ["not"]}),
    ("NOT", "postfix", 60, "left", [1, 0], False, "not",
     {"text": ["'", "’"], "math": ["′"]}),
    ("AND", "infix", 50, "left", [0, 0, 0, 1], True, "and",
     {"text": ["*", ".", "·"], "prog": ["&", "&&"], "math": ["∧"], "word": ["and"]}),
    ("NAND", "infix", 50, "left", [1, 1, 1, 0], False, "nand",
     {"prog": ["~&"], "math": ["↑"], "word": ["nand"]}),
    ("XOR", "infix", 40, "left", [0, 1, 1, 0], True, "xor",
     {"text": ["^", "⊕"], "prog": ["^"], "math": ["⊕"], "word": ["xor"]}),
    ("XNOR", "infix", 40, "left", [1, 0, 0, 1], False, "xnor",
     {"text": ["⊙"], "prog": ["~^", "=="], "word": ["xnor"]}),
    ("OR", "infix", 30, "left", [0, 1, 1, 1], True, "or",
     {"text": ["+", "|"], "prog": ["|", "||"], "math": ["∨"], "word": ["or"]}),
    ("NOR", "infix", 30, "left", [1, 0, 0, 0], False, "nor",
     {"prog": ["~|"], "math": ["↓"], "word": ["nor"]}),
    ("IMP", "infix", 20, "right", [1, 1, 0, 1], False, "box",
     {"text": ["->", "=>"], "prog": ["->", "=>"], "math": ["→"], "word": ["imp", "implies"]}),
    ("EQV", "infix", 10, "left", [1, 0, 0, 1], False, "xnor",
     {"text": ["<->"], "math": ["↔", "≡"], "word": ["eqv", "iff"]}),
]


def _build(name: str, description: str, styles: tuple[str, ...], implicit: str | None) -> PresetDef:
    operators = []
    for op_name, fixity, prec, assoc, table, nary, shape, by_style in _MASTER:
        symbols: list[str] = []
        for style in styles:
            for sym in by_style.get(style, []):
                if sym not in symbols:
                    symbols.append(sym)
        if symbols:
            operators.append(
                OperatorDef(name=op_name, fixity=fixity, symbols=symbols, precedence=prec,
                            assoc=assoc, table=table, nary=nary, shape=shape)
            )
    return PresetDef(name=name, description=description, operators=operators, implicit=implicit)


BUILTIN_PRESETS: dict[str, PresetDef] = {
    "universal": _build(
        "universal",
        "Accepts every notation below at once. Good default.",
        ("text", "prog", "math", "word"),
        "AND",
    ),
    "textbook": _build(
        "textbook",
        "Course style: x' for NOT, + for OR, xy or x*y for AND, ^ for XOR, plus word operators.",
        ("text", "word"),
        "AND",
    ),
    "programming": _build(
        "programming",
        "C/Python style: ! & && | || ^ ~& ~| ~^ and word operators. No implicit AND.",
        ("prog", "word"),
        None,
    ),
}

DEFAULT_PRESET = "universal"


def _std(name: str, fixity: str) -> OperatorDef:
    return next(op for op in BUILTIN_PRESETS["universal"].operators if op.name == name and op.fixity == fixity)


# Standard gates used when the backend itself builds a circuit (SOP / POS modes),
# independent of whatever preset the user typed the expression in.
STD_NOT = _std("NOT", "prefix")
STD_AND = _std("AND", "infix")
STD_OR = _std("OR", "infix")
