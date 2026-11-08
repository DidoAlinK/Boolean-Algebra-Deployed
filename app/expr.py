"""The expression tree used by the simplifier.

It is different from the parser tree (ast_nodes.py) on purpose:

  * AND and OR hold a LIST of operands:  a + b + c  is  Or(a, b, c), not Or(Or(a, b), c).
  * Only AND, OR and NOT exist. Any other operator (XOR, NAND, a custom one...) becomes a Gate,
    which the simplifier rewrites into AND/OR/NOT as its very first steps.

The classes are "frozen dataclasses": they cannot be changed after creation, and two nodes with the same
content are equal (Var("x") == Var("x")). A rewrite never edits a tree, it builds a new one, so the
old tree stays valid and can be printed as the "before" of a step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from . import ast_nodes as parsed


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    value: int


@dataclass(frozen=True)
class Not:
    child: "Node"


@dataclass(frozen=True)
class And:
    items: tuple["Node", ...]


@dataclass(frozen=True)
class Or:
    items: tuple["Node", ...]


@dataclass(frozen=True)
class Gate:
    """Any operator that is not AND, OR or NOT. `table` is its truth table (see presets.py)."""

    name: str
    table: tuple[int, ...]
    args: tuple["Node", ...]


Node = Union[Var, Const, Not, And, Or, Gate]

_AND_TABLE = (0, 0, 0, 1)
_OR_TABLE = (0, 1, 1, 1)
_NOT_TABLE = (1, 0)


def make(kind: type, items: list) -> Node:
    """Builds And(...) or Or(...) from a list. Operands of the same kind are merged into the list
    (a + (b + c) becomes a + b + c) and a list with one operand is just that operand."""
    flat: list[Node] = []
    for item in items:
        if isinstance(item, kind):
            flat.extend(item.items)
        else:
            flat.append(item)
    if len(flat) == 1:
        return flat[0]
    return kind(tuple(flat))


# ---------------------------------------------------------------------------------------------
# From the parser tree
# ---------------------------------------------------------------------------------------------
def from_parsed(node: parsed.Node) -> Node:
    """Converts the parser's tree. Operators are recognised by their TRUTH TABLE, not their name,
    so a custom operator whose table is AND's table is treated as AND."""
    if isinstance(node, parsed.Var):
        return Var(node.name)
    if isinstance(node, parsed.Const):
        return Const(node.value)
    if isinstance(node, parsed.Unary):
        child = from_parsed(node.operand)
        table = tuple(node.op.table)
        if table == _NOT_TABLE:
            return Not(child)
        return Gate(node.op.name, table, (child,))

    table = tuple(node.op.table)
    if table in (_AND_TABLE, _OR_TABLE):
        kind = And if table == _AND_TABLE else Or
        operands = _chain_operands(node, table)
        return make(kind, [from_parsed(operand) for operand in operands])
    return Gate(node.op.name, table, (from_parsed(node.left), from_parsed(node.right)))


def _chain_operands(node: parsed.Binary, table: tuple[int, ...]) -> list[parsed.Node]:
    """a + b + c is stored by the parser as Or(Or(a, b), c). This returns [a, b, c] using a stack
    (not recursion) so a chain of 1000 terms cannot overflow Python's recursion limit."""
    operands: list[parsed.Node] = []
    stack: list[parsed.Node] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, parsed.Binary) and tuple(current.op.table) == table:
            stack.append(current.right)     # right first, so the left side is popped first
            stack.append(current.left)
        else:
            operands.append(current)
    return operands


# ---------------------------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------------------------
def children(node: Node) -> tuple[Node, ...]:
    if isinstance(node, Not):
        return (node.child,)
    if isinstance(node, (And, Or)):
        return node.items
    if isinstance(node, Gate):
        return node.args
    return ()


def literal_count(node: Node) -> int:
    """How many times a variable is written. x'y + xy' has 4. This is the number we try to reduce."""
    if isinstance(node, Var):
        return 1
    return sum(literal_count(child) for child in children(node))


def node_count(node: Node) -> int:
    return 1 + sum(node_count(child) for child in children(node))


# ---------------------------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------------------------
def canon(node: Node):
    """A form of the node that ignores the ORDER of AND/OR operands, so b + a and a + b give the same
    value. This is how rules recognise 'the same expression' (it uses commutativity P2 and
    associativity P3 silently, and the step names them in its "also used" list).

    It returns nested tuples, which can be compared, sorted and put in sets."""
    if isinstance(node, Var):
        return ("v", node.name)
    if isinstance(node, Const):
        return ("c", node.value)
    if isinstance(node, Not):
        return ("n", canon(node.child))
    if isinstance(node, (And, Or)):
        tag = "a" if isinstance(node, And) else "o"
        parts: list = []
        for item in node.items:
            inner = canon(item)
            if inner[0] == tag:             # a nested group of the same kind is merged (P3)
                parts.extend(inner[1])
            else:
                parts.append(inner)
        return (tag, tuple(sorted(parts)))
    return ("g", node.name, node.table, tuple(canon(arg) for arg in node.args))


def negate(node: Node) -> Node:
    """The complement of a node with the negations pushed down to the variables (De Morgan).
    Only used to COMPARE ('is this the complement of that?'), never shown to the user."""
    if isinstance(node, Var):
        return Not(node)
    if isinstance(node, Const):
        return Const(1 - node.value)
    if isinstance(node, Not):
        return node.child
    if isinstance(node, And):
        return Or(tuple(negate(item) for item in node.items))
    if isinstance(node, Or):
        return And(tuple(negate(item) for item in node.items))
    return Not(node)


def is_complement(a: Node, b: Node) -> bool:
    return canon(negate(a)) == canon(b)


# ---------------------------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------------------------
# Letters written next to each other are read by the lab as ONE word, so the product n.o.r must not be
# printed "nor" (that is the NOR operator). Such products are printed with a dot between the letters.
_WORD_OPERATORS = {"and", "or", "not", "nand", "nor", "xor", "xnor", "imp", "implies", "eqv", "iff"}

# Two invisible marker characters. They are put around the part of the text we want to highlight,
# then removed again by render(), which reports where they were as a (start, end) pair.
_MARK_START = "\ue000"
_MARK_END = "\ue001"


def render(node: Node, path: list[int] | None = None) -> tuple[str, tuple[int, int] | None]:
    """Text of the expression, always in textbook notation: x' for NOT, + for OR, xy for AND.

    `path` is an optional list of child positions leading to one node, e.g. [0, 2] is 'the third
    operand of the first operand'. If given, the second value returned is the (start, end) of that node's
    text, so the frontend can highlight it. Otherwise it is None."""
    text = _fmt(node, path)
    if path is None:
        return text, None
    start = text.index(_MARK_START)
    text = text.replace(_MARK_START, "", 1)
    end = text.index(_MARK_END)
    text = text.replace(_MARK_END, "", 1)
    return text, (start, end)


def text_of(node: Node) -> str:
    return render(node)[0]


def _fmt(node: Node, path: list[int] | None) -> str:
    if path is not None and len(path) == 0:         # this is the node to mark
        return _MARK_START + _fmt(node, None) + _MARK_END

    def below(position: int) -> list[int] | None:
        """The path to hand to the child at `position` (None if the marked node is not inside it)."""
        if path is not None and path[0] == position:
            return path[1:]
        return None

    if isinstance(node, Var):
        return node.name
    if isinstance(node, Const):
        return str(node.value)
    if isinstance(node, Not):
        inner = _fmt(node.child, below(0))
        if isinstance(node.child, (Var, Const, Not)):
            return inner + "'"
        return "(" + inner + ")'"
    if isinstance(node, And):
        return _fmt_and(node, below)
    if isinstance(node, Or):
        parts = [_wrap_gate(item, _fmt(item, below(i))) for i, item in enumerate(node.items)]
        return " + ".join(parts)
    return _fmt_gate(node, below)


def _wrap_gate(item: Node, text: str) -> str:
    return "(" + text + ")" if isinstance(item, Gate) else text


def _fmt_and(node: And, below) -> str:
    items = node.items
    has_constant = any(isinstance(item, Const) for item in items)

    # Find the gaps between two plain letters that must get a dot (see _WORD_OPERATORS).
    dotted = [False] * len(items)                   # dotted[k] = put a dot BEFORE item k
    k = 0
    while k < len(items):
        if isinstance(items[k], Var):
            end = k
            while end + 1 < len(items) and isinstance(items[end + 1], Var):
                end += 1
            letters = "".join(items[m].name for m in range(k, end + 1))
            if end > k and letters in _WORD_OPERATORS:
                for m in range(k + 1, end + 1):
                    dotted[m] = True
            k = end + 1
        else:
            k += 1

    pieces: list[str] = []
    for i, item in enumerate(items):
        text = _fmt(item, below(i))
        if isinstance(item, (Or, Gate)):
            text = "(" + text + ")"
        if i > 0 and (has_constant or dotted[i]):
            pieces.append("·")
        pieces.append(text)
    return "".join(pieces)


def _fmt_gate(node: Gate, below) -> str:
    def operand(position: int) -> str:
        arg = node.args[position]
        text = _fmt(arg, below(position))
        simple = isinstance(arg, (Var, Const)) or (isinstance(arg, Not) and isinstance(arg.child, Var))
        return text if simple else "(" + text + ")"

    name = node.name.lower()
    if len(node.args) == 1:
        return f"{name}({_fmt(node.args[0], below(0))})"
    return f"{operand(0)} {name} {operand(1)}"


# ---------------------------------------------------------------------------------------------
# Evaluating (used to double-check a result)
# ---------------------------------------------------------------------------------------------
def variable_masks(variables: list[str]) -> tuple[dict[str, int], int]:
    """One big integer per variable, holding that variable's column of the truth table:
    bit i of the integer is the variable's value on row i. The FIRST variable is the most significant
    bit of the row number (same convention as the rest of the app).

    With these, "x AND y" for all rows at once is just `mask_x & mask_y`, which is why checking
    4096 rows costs almost nothing. Returns (masks, full) where `full` has a 1 for every row."""
    n = len(variables)
    rows = 1 << n
    full = (1 << rows) - 1
    masks: dict[str, int] = {}
    for k, name in enumerate(variables):
        block = 1 << (n - 1 - k)                    # rows with the variable at 0, then at 1, repeated
        unit = ((1 << block) - 1) << block          # `block` zeros (low bits) then `block` ones
        mask = 0
        for start in range(0, rows, 2 * block):
            mask |= unit << start
        masks[name] = mask
    return masks, full


def table_bits(table: tuple[int, ...] | list[int], args: list[int], full: int) -> int:
    """Applies an operator's truth table to whole columns of bits at once."""
    result = 0
    if len(table) == 2:
        if table[0]:
            result |= full ^ args[0]
        if table[1]:
            result |= args[0]
        return result
    left, right = args
    for a in (0, 1):
        for b in (0, 1):
            if table[(a << 1) | b]:
                part_a = left if a else full ^ left
                part_b = right if b else full ^ right
                result |= part_a & part_b
    return result


def evaluate_bits(node: Node, masks: dict[str, int], full: int) -> int:
    if isinstance(node, Var):
        return masks[node.name]
    if isinstance(node, Const):
        return full if node.value else 0
    if isinstance(node, Not):
        return full ^ evaluate_bits(node.child, masks, full)
    if isinstance(node, And):
        result = full
        for item in node.items:
            result &= evaluate_bits(item, masks, full)
        return result
    if isinstance(node, Or):
        result = 0
        for item in node.items:
            result |= evaluate_bits(item, masks, full)
        return result
    return table_bits(node.table, [evaluate_bits(arg, masks, full) for arg in node.args], full)


def evaluate_parsed_bits(root: parsed.Node, masks: dict[str, int], full: int) -> int:
    """Same as evaluate_bits but for the parser's own tree, walked with a stack instead of recursion.
    The check compares this (the expression exactly as parsed) with the simplified result, so it does not
    depend on the simplifier's own conversion being right."""
    values: dict[int, int] = {}
    stack: list[tuple[parsed.Node, bool]] = [(root, False)]
    while stack:
        node, children_done = stack.pop()
        if isinstance(node, parsed.Var):
            values[id(node)] = masks[node.name]
        elif isinstance(node, parsed.Const):
            values[id(node)] = full if node.value else 0
        elif not children_done:
            stack.append((node, True))
            if isinstance(node, parsed.Unary):
                stack.append((node.operand, False))
            else:
                stack.append((node.left, False))
                stack.append((node.right, False))
        elif isinstance(node, parsed.Unary):
            values[id(node)] = table_bits(node.op.table, [values[id(node.operand)]], full)
        else:
            values[id(node)] = table_bits(node.op.table, [values[id(node.left)], values[id(node.right)]], full)
    return values[id(root)]
