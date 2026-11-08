"""Computes the value of an expression for given variable values."""
from __future__ import annotations

from .ast_nodes import Binary, Const, Node, Unary, Var


def evaluate(node: Node, env: dict[str, int]) -> int:
    if isinstance(node, Var):
        return env[node.name]
    if isinstance(node, Const):
        return node.value
    if isinstance(node, Unary):
        return node.op.table[evaluate(node.operand, env)]
    # binary: the operator's table is indexed by (left << 1) | right
    return node.op.table[(evaluate(node.left, env) << 1) | evaluate(node.right, env)]


def row_bits(index: int, n_vars: int) -> list[int]:
    """Row 6 of a 3-variable table is [1, 1, 0]: the FIRST variable is the most significant bit."""
    return [(index >> (n_vars - 1 - k)) & 1 for k in range(n_vars)]


def truth_table_outputs(node: Node, variables: list[str]) -> list[int]:
    n = len(variables)
    outputs = []
    for index in range(1 << n):
        env = dict(zip(variables, row_bits(index, n)))
        outputs.append(evaluate(node, env))
    return outputs
