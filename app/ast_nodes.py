"""The expression tree. The parser builds it, everything else reads it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .presets import OperatorDef


@dataclass
class Var:
    name: str


@dataclass
class Const:
    value: int


@dataclass
class Unary:
    op: OperatorDef
    operand: "Node"


@dataclass
class Binary:
    op: OperatorDef
    left: "Node"
    right: "Node"


Node = Union[Var, Const, Unary, Binary]


def variables_in(node: Node) -> set[str]:
    if isinstance(node, Var):
        return {node.name}
    if isinstance(node, Const):
        return set()
    if isinstance(node, Unary):
        return variables_in(node.operand)
    return variables_in(node.left) | variables_in(node.right)


def flatten(node: Node, op_name: str) -> list[Node]:
    """x.y.z is stored as AND(AND(x,y),z); this returns [x, y, z] for the circuit and the text view.
    Uses a stack instead of recursion so very long chains cannot overflow Python's recursion limit."""
    operands: list[Node] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Binary) and current.op.name == op_name and current.op.nary:
            stack.append(current.right)   # right first, so the left side is popped (and kept) first
            stack.append(current.left)
        else:
            operands.append(current)
    return operands


def to_structure(node: Node) -> str:
    """Shows how the parser grouped things, e.g. OR(AND(NOT(x), y), z)."""
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Const):
        return str(node.value)
    if isinstance(node, Unary):
        return f"{node.op.name}({to_structure(node.operand)})"
    parts = flatten(node, node.op.name) if node.op.nary else [node.left, node.right]
    return f"{node.op.name}({', '.join(to_structure(p) for p in parts)})"


def to_tree(node: Node) -> dict:
    """Plain-dict version of the tree for the JSON response."""
    if isinstance(node, Var):
        return {"type": "var", "name": node.name}
    if isinstance(node, Const):
        return {"type": "const", "value": node.value}
    if isinstance(node, Unary):
        return {"type": "unary", "op": node.op.name, "operand": to_tree(node.operand)}
    return {"type": "binary", "op": node.op.name, "left": to_tree(node.left), "right": to_tree(node.right)}
