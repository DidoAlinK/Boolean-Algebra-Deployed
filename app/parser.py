"""Pratt parser (precedence climbing).

Precedence is NOT hard-coded here: every operator carries a number (higher = binds tighter)
and the loop in `_expr` only consumes an operator if its number is >= min_prec.
That is why presets can add or re-order operators without touching this file.
"""
from __future__ import annotations

from .ast_nodes import Binary, Const, Node, Unary, Var
from .config import MAX_NESTING
from .errors import ParseError
from .presets import CompiledPreset
from .tokenizer import Token


class Parser:
    def __init__(self, tokens: list[Token], preset: CompiledPreset) -> None:
        self.tokens = tokens
        self.preset = preset
        self.i = 0

    # -- token helpers ------------------------------------------------------
    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _name(self, letter: str) -> str:
        return letter.lower()       # A and a are the same variable, always shown lowercase

    def _starts_factor(self, tok: Token) -> bool:
        """Can this token begin a new operand? Used for implicit AND (xy)."""
        if tok.kind in ("VAR", "CONST", "LPAREN"):
            return True
        return tok.kind == "OP" and tok.op is not None and tok.op.fixity == "prefix"

    # -- grammar ------------------------------------------------------------
    def parse(self) -> Node:
        if self._peek().kind == "END":
            raise ParseError("empty expression", 0)
        node = self._expr(0, 0)
        tok = self._peek()
        if tok.kind != "END":
            if tok.kind == "RPAREN":
                raise ParseError("unexpected ')'", tok.pos)
            if self.preset.implicit_op is None and tok.kind in ("VAR", "CONST", "LPAREN"):
                raise ParseError(
                    f"unexpected {tok.text!r}: this preset has no implicit AND, put an operator between terms",
                    tok.pos,
                )
            raise ParseError(f"unexpected {tok.text!r}", tok.pos)
        return node

    def _expr(self, min_prec: int, depth: int) -> Node:
        if depth > MAX_NESTING:
            raise ParseError("expression is nested too deeply", self._peek().pos)

        left = self._prefix(depth)

        while True:
            tok = self._peek()

            if tok.kind == "OP" and tok.op.fixity == "postfix":
                if tok.op.precedence < min_prec:
                    break
                self._advance()
                left = Unary(tok.op, left)
                continue

            if tok.kind == "OP" and tok.op.fixity == "infix":
                op = tok.op
                if op.precedence < min_prec:
                    break
                self._advance()
                next_min = op.precedence + 1 if op.assoc == "left" else op.precedence
                right = self._expr(next_min, depth + 1)
                left = Binary(op, left, right)
                continue

            implicit = self.preset.implicit_op
            if implicit is not None and self._starts_factor(tok):
                if implicit.precedence < min_prec:
                    break
                right = self._expr(implicit.precedence + 1, depth + 1)
                left = Binary(implicit, left, right)
                continue

            break

        return left

    def _prefix(self, depth: int) -> Node:
        tok = self._advance()

        if tok.kind == "VAR":
            return Var(self._name(tok.text))
        if tok.kind == "CONST":
            return Const(int(tok.text))
        if tok.kind == "LPAREN":
            inner = self._expr(0, depth + 1)
            closing = self._peek()
            if closing.kind != "RPAREN":
                raise ParseError("missing ')'", closing.pos)
            self._advance()
            return inner
        if tok.kind == "OP" and tok.op.fixity == "prefix":
            operand = self._expr(tok.op.precedence, depth + 1)
            return Unary(tok.op, operand)
        if tok.kind == "END":
            raise ParseError("unexpected end of expression", tok.pos)
        if tok.kind == "RPAREN":
            raise ParseError("unexpected ')'", tok.pos)
        raise ParseError(f"{tok.text!r} needs something on its left", tok.pos)
