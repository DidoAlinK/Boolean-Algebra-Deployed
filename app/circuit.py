"""Turns an expression tree into a circuit: gates, wires and a grid layout.

The backend decides WHAT is connected and WHERE it sits on a grid (column = depth,
row = slot in that column, plus a route of waypoints for wires that skip columns).
The frontend only draws it.

Equal sub-expressions share one gate (x' used twice is one NOT gate), and chains of
AND / OR / XOR become one multi-input gate, like in the textbook drawings.
"""
from __future__ import annotations

from .ast_nodes import Binary, Const, Node, Unary, Var, flatten
from .config import MAX_CIRCUIT_NODES
from .presets import STD_AND, STD_NOT, STD_OR, OperatorDef


class CircuitTooLarge(Exception):
    pass


class _Builder:
    def __init__(self, limit: int) -> None:
        self.nodes: list[dict] = []
        self.keys: dict[tuple, str] = {}
        self.limit = limit

    def _new(self, **fields) -> str:
        if len(self.nodes) >= self.limit:
            raise CircuitTooLarge()
        node_id = f"n{len(self.nodes)}"
        self.nodes.append({"id": node_id, "gate": None, "shape": None, "table": None,
                           "nary": False, "inputs": [], **fields})
        return node_id

    def build(self, node: Node) -> str:
        if isinstance(node, Var):
            return self._shared(("input", node.name), kind="input", label=node.name)
        if isinstance(node, Const):
            return self._shared(("const", node.value), kind="const", label=str(node.value))
        if isinstance(node, Unary):
            return self._gate(node.op, [self.build(node.operand)])
        operands = flatten(node, node.op.name) if node.op.nary else [node.left, node.right]
        return self._gate(node.op, [self.build(o) for o in operands])

    def _shared(self, key: tuple, **fields) -> str:
        if key not in self.keys:
            self.keys[key] = self._new(**fields)
        return self.keys[key]

    def _gate(self, op: OperatorDef, inputs: list[str]) -> str:
        commutative = op.fixity == "infix" and op.table[1] == op.table[2]
        key = ("gate", op.name, tuple(op.table), tuple(sorted(inputs)) if commutative else tuple(inputs))
        return self._shared(key, kind="gate", label=op.name, gate=op.name, shape=op.shape,
                            table=list(op.table), nary=op.nary, inputs=inputs)


def _separate(desired: list[float]) -> list[float]:
    """Closest positions to `desired` that keep the given order and are at least 1 apart
    (pool-adjacent-violators on the shifted values)."""
    blocks: list[list[float]] = []            # [sum, count]
    for i, d in enumerate(desired):
        blocks.append([d - i, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    flat: list[float] = []
    for total, count in blocks:
        flat.extend([total / count] * int(count))
    return [v + i for i, v in enumerate(flat)]


class _Item:
    """Something that occupies a slot in a column: a real node, or a waypoint of a long wire."""
    __slots__ = ("key", "col", "preds", "succs")

    def __init__(self, key, col: int) -> None:
        self.key = key
        self.col = col
        self.preds: list = []
        self.succs: list = []


def _layout(nodes: list[dict], edges: list[dict], variables: list[str]) -> tuple[int, float]:
    """Layered layout.

    Column = longest path from an input. A wire that skips columns gets one waypoint per skipped
    column (shared between wires leaving the same source), so it owns a free lane and never runs
    through a gate. Orders inside columns are improved with barycenter sweeps, then vertical
    positions are pulled towards the average of the neighbours (straighter wires) while keeping
    every slot at least 1 apart. Fills node["col"], node["row"] and edge["route"].
    """
    level: dict[str, int] = {}
    for node in nodes:
        level[node["id"]] = 0 if not node["inputs"] else 1 + max(level[i] for i in node["inputs"])

    items: dict = {n["id"]: _Item(n["id"], level[n["id"]]) for n in nodes}

    def link(a, b) -> None:
        if b not in items[a].succs:
            items[a].succs.append(b)
        if a not in items[b].preds:
            items[b].preds.append(a)

    chains: list[list] = []
    for edge in edges:
        source, target = edge["source"], edge["target"]
        previous = source
        chain = []
        for lvl in range(level[source] + 1, level[target]):
            key = ("wp", source, lvl)
            if key not in items:
                items[key] = _Item(key, lvl)
            link(previous, key)
            chain.append(key)
            previous = key
        link(previous, target)
        chains.append(chain)

    ncols = max(item.col for item in items.values()) + 1
    order: list[list[_Item]] = [[] for _ in range(ncols)]
    for item in items.values():
        order[item.col].append(item)

    by_id = {n["id"]: n for n in nodes}

    def input_rank(item: _Item) -> tuple:
        node = by_id[item.key]
        return (0, variables.index(node["label"])) if node["kind"] == "input" else (1, int(node["label"]))

    order[0].sort(key=input_rank)                      # input rail order is fixed: alphabetical, then constants

    pos: dict = {}

    def refresh(col: int) -> None:
        for i, item in enumerate(order[col]):
            pos[item.key] = float(i)

    for c in range(ncols):
        refresh(c)

    def barycenter(neighbours: list, fallback: float) -> float:
        return sum(pos[k] for k in neighbours) / len(neighbours) if neighbours else fallback

    for _ in range(4):                                  # reduce crossings
        for c in range(1, ncols):
            order[c].sort(key=lambda it: barycenter(it.preds, pos[it.key]))
            refresh(c)
        for c in range(ncols - 2, 0, -1):
            order[c].sort(key=lambda it: barycenter(it.succs, pos[it.key]))
            refresh(c)

    y = dict(pos)
    for _ in range(12):                                 # straighten wires
        for c in list(range(ncols)) + list(range(ncols - 1, -1, -1)):
            desired = []
            for item in order[c]:
                around = item.preds + item.succs
                desired.append(sum(y[k] for k in around) / len(around) if around else y[item.key])
            for item, value in zip(order[c], _separate(desired)):
                y[item.key] = value

    low = min(y.values())
    for key in y:
        y[key] = round(y[key] - low, 3)

    for node in nodes:
        node["col"] = level[node["id"]]
        node["row"] = y[node["id"]]
    for edge, chain in zip(edges, chains):
        edge["route"] = [{"col": items[k].col, "row": y[k]} for k in chain]

    return ncols, round(max(y.values()) + 1, 3)


def build_circuit(tree: Node, variables: list[str], mode: str, max_nodes: int = MAX_CIRCUIT_NODES) -> dict:
    builder = _Builder(max_nodes)
    root = builder.build(tree)
    output = builder._new(kind="output", label="F", inputs=[root])

    edges = []
    for node in builder.nodes:
        for port, source in enumerate(node["inputs"]):
            edges.append({"source": source, "target": node["id"], "port": port, "ports": len(node["inputs"])})

    cols, rows = _layout(builder.nodes, edges, variables)

    return {
        "mode": mode,
        "nodes": builder.nodes,
        "edges": edges,
        "cols": cols,
        "rows": rows,
        "gate_count": sum(1 for n in builder.nodes if n["kind"] == "gate"),
        "output": output,
    }


# -- circuits synthesised from minterms / maxterms (the textbook two-level drawings) ----------

def _literal(name: str, negated: bool) -> Node:
    return Unary(STD_NOT, Var(name)) if negated else Var(name)


def _fold(op: OperatorDef, items: list[Node]) -> Node:
    """Joins items with a binary operator as a BALANCED tree. A flat left-to-right chain of 2048
    minterms would be 2048 levels deep, which is slow to walk and overflows recursion."""
    if len(items) == 1:
        return items[0]
    middle = len(items) // 2
    return Binary(op, _fold(op, items[:middle]), _fold(op, items[middle:]))


def sop_tree(indices: list[int], variables: list[str], bits_of) -> Node:
    """OR of AND terms: one AND gate per minterm, one OR gate at the end."""
    if not indices:
        return Const(0)
    terms = []
    for i in indices:
        bits = bits_of(i, len(variables))
        literals = [_literal(v, b == 0) for v, b in zip(variables, bits)]
        terms.append(_fold(STD_AND, literals) if literals else Const(1))
    return _fold(STD_OR, terms)


def pos_tree(indices: list[int], variables: list[str], bits_of) -> Node:
    """AND of OR terms: one OR gate per maxterm, one AND gate at the end."""
    if not indices:
        return Const(1)
    terms = []
    for i in indices:
        bits = bits_of(i, len(variables))
        literals = [_literal(v, b == 1) for v, b in zip(variables, bits)]
        terms.append(_fold(STD_OR, literals) if literals else Const(0))
    return _fold(STD_AND, terms)


def simulate(circuit: dict, assignment: dict[str, int]) -> int:
    """Runs the circuit for one input assignment. Used by the tests to prove the drawing is correct."""
    values: dict[str, int] = {}
    for node in circuit["nodes"]:           # nodes are stored in dependency order
        kind = node["kind"]
        if kind == "input":
            value = assignment[node["label"]]
        elif kind == "const":
            value = int(node["label"])
        elif kind == "gate":
            ins = [values[i] for i in node["inputs"]]
            table = node["table"]
            if len(table) == 2:
                value = table[ins[0]]
            else:
                value = ins[0]
                for nxt in ins[1:]:
                    value = table[(value << 1) | nxt]
        else:
            value = values[node["inputs"][0]]
        values[node["id"]] = value
    return values[circuit["output"]]
