"""Turns the typed text into a flat list of tokens.

    x'y + z   ->   VAR(x) OP(') VAR(y) OP(+) VAR(z) END

Rules:
  * letters are variables, one letter each:  xy = x and y
  * a whole run of letters that is a word operator (and, nor, implies...) is an operator
    (so word operators need spaces around them: "x nor y")
  * symbols are matched longest-first, so "~&" wins over "~"
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ParseError
from .presets import CompiledPreset, OperatorDef


@dataclass
class Token:
    kind: str                       # VAR, CONST, LPAREN, RPAREN, OP, END
    text: str
    pos: int                        # 0-based index into the original text
    op: OperatorDef | None = None


def _is_ascii_letter(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def tokenize(text: str, preset: CompiledPreset) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)

    while i < n:
        c = text[i]

        if c.isspace():
            i += 1
        elif c == "(":
            tokens.append(Token("LPAREN", c, i))
            i += 1
        elif c == ")":
            tokens.append(Token("RPAREN", c, i))
            i += 1
        elif c in "01":
            tokens.append(Token("CONST", c, i))
            i += 1
        elif _is_ascii_letter(c):
            j = i
            while j < n and _is_ascii_letter(text[j]):
                j += 1
            run = text[i:j]
            op = preset.word_ops.get(run.lower())
            if op is not None:
                tokens.append(Token("OP", run, i, op))
            else:
                for k in range(i, j):
                    tokens.append(Token("VAR", text[k], k))
            i = j
        else:
            for sym in preset.symbols_by_length:
                if text.startswith(sym, i):
                    tokens.append(Token("OP", sym, i, preset.by_symbol[sym]))
                    i += len(sym)
                    break
            else:
                raise ParseError(f"unknown character {c!r}", i)

    tokens.append(Token("END", "", n))
    return tokens
