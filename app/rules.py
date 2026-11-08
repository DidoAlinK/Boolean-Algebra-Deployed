"""The rules the simplifier may use, named after the course sheet (postulates P1-P5, theorems T1-T6).

Every sheet rule comes in two dual versions: (a) is about "+" (OR) and (b) is about "." (AND), with
0 and 1 swapped. The code below handles both with one function by describing the two versions in a
small `Side` record (see SUM and PRODUCT), so there is no copy-pasted "b" version to get out of sync.

A rule is a function  rule(node, budget) -> Rewrite | None.
It looks ONLY at the node it is given (never at its parents), and returns None when it does not apply.
That is what lets the engine remember "nothing inside this subtree matches" and skip it next time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .expr import (
    And, Const, Gate, Node, Not, Or, Var, canon, is_complement, make, negate, text_of,
)


# ---------------------------------------------------------------------------------------------
# Budget: protects the server from expressions that would run forever or grow without limit
# ---------------------------------------------------------------------------------------------
class BudgetExceeded(Exception):
    """Raised when the work is cut short. `reason` is "time", "steps" or "size"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Budget:
    def __init__(self, seconds: float, max_steps: int, max_nodes: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.deadline = clock() + seconds
        self.max_steps = max_steps
        self.max_nodes = max_nodes
        self._ticks = 0

    def check_time(self) -> None:
        if self.clock() > self.deadline:
            raise BudgetExceeded("time")

    def tick(self) -> None:
        """Called inside loops. Looking at the clock every time would be slow, so only every 256th call."""
        self._ticks += 1
        if self._ticks % 256 == 0:
            self.check_time()


# ---------------------------------------------------------------------------------------------
# The catalogue shown to the user
# ---------------------------------------------------------------------------------------------
def _rule(rid, name, equation, dual, on_sheet=True, note=""):
    return {"id": rid, "name": name, "equation": equation, "dual": dual, "on_sheet": on_sheet, "note": note}


RULES: dict[str, dict] = {r["id"]: r for r in [
    _rule("P1a", "Existence of 1 and 0", "x + 0 = x", "P1b"),
    _rule("P1b", "Existence of 1 and 0", "x·1 = x", "P1a"),
    _rule("P2a", "Commutativity", "x + y = y + x", "P2b"),
    _rule("P2b", "Commutativity", "x·y = y·x", "P2a"),
    _rule("P3a", "Associativity", "x + (y + z) = (x + y) + z", "P3b"),
    _rule("P3b", "Associativity", "x·(y·z) = (x·y)·z", "P3a"),
    _rule("P4a", "Distributivity", "x + (y·z) = (x + y)·(x + z)", "P4b"),
    _rule("P4b", "Distributivity", "x·(y + z) = x·y + x·z", "P4a"),
    _rule("P5a", "Complementation", "x + x' = 1", "P5b"),
    _rule("P5b", "Complementation", "x·x' = 0", "P5a"),
    _rule("T1a", "Idempotence", "x + x = x", "T1b"),
    _rule("T1b", "Idempotence", "x·x = x", "T1a"),
    _rule("T2a", "Property of 1 and 0", "x + 1 = 1", "T2b"),
    _rule("T2b", "Property of 1 and 0", "x·0 = 0", "T2a"),
    _rule("T3a", "Absorption", "x + x·y = x", "T3b"),
    _rule("T3b", "Absorption", "x·(x + y) = x", "T3a"),
    _rule("T4a", "Half-absorption", "x + x'·y = x + y", "T4b"),
    _rule("T4b", "Half-absorption", "x·(x' + y) = x·y", "T4a"),
    _rule("T5a", "De Morgan's law", "(x + y)' = x'·y'", "T5b"),
    _rule("T5b", "De Morgan's law", "(x·y)' = x' + y'", "T5a"),
    _rule("T6a", "Consensus", "x·y + x'·z + y·z = x·y + x'·z", "T6b"),
    _rule("T6b", "Consensus", "(x + y)(x' + z)(y + z) = (x + y)(x' + z)", "T6a"),
    _rule("INV", "Double complement", "(x')' = x", "", False,
          "Not on the sheet. It follows from P5: the complement of x is unique, and x is a complement of x'."),
    _rule("NOT01", "Complement of 0 and 1", "1' = 0 and 0' = 1", "", False,
          "Not on the sheet. It follows from P5 and P1."),
    _rule("DEF", "Operator definition", "x ⊕ y = x·y' + x'·y, (x·y)↑ = (x·y)', ...", "", False,
          "XOR, NAND, NOR, XNOR, IMP... are not in the postulates, so they are first written with AND, OR and NOT."),
]}


def phase_of(rule_id: str, direction: str) -> str:
    if rule_id == "DEF":
        return "definitions"
    if rule_id in ("NOT01", "INV", "T5a", "T5b"):
        return "negations"
    if rule_id in ("P4a", "P4b"):
        return "expand" if direction == "forward" else "factor"
    return "reduce"


# ---------------------------------------------------------------------------------------------
# What a rule returns
# ---------------------------------------------------------------------------------------------
@dataclass
class Rewrite:
    rule: str                       # catalogue id, e.g. "T3a"
    new: Node                       # replacement for the node the rule was given
    focus_before: str               # the part that matched, as text
    focus_after: str                # what it became
    explain: str                    # one sentence in plain words
    also: list[str] = field(default_factory=list)   # supporting rules (P2, P3) used to bring terms together
    direction: str = "forward"      # "backward" = a distributive law read right to left (factoring)


def _short(text: str, limit: int = 140) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------------------------
# The two dual versions of a rule
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Side:
    outer: type          # the node the rule looks at: Or for the (a) version, And for (b)
    inner: type          # what its operands are made of: And for (a), Or for (b)
    suffix: str          # "a" or "b"
    identity: int        # 0 for a sum, 1 for a product (x + 0 = x, x.1 = x)
    absorbing: int       # 1 for a sum, 0 for a product (x + 1 = 1, x.0 = 0)
    word: str            # "sum" / "product", used in sentences
    part: str            # "term" / "factor"


SUM = Side(Or, And, "a", 0, 1, "sum", "term")
PRODUCT = Side(And, Or, "b", 1, 0, "product", "factor")


def side_of(node: Node) -> Side:
    return SUM if isinstance(node, Or) else PRODUCT


def _parts(item: Node, side: Side) -> tuple[Node, ...]:
    """The operands of a term. In a sum, x'y has the parts (x', y) and a lone x has the part (x)."""
    return item.items if isinstance(item, side.inner) else (item,)


def _group(kind: type, nodes: list[Node]) -> str:
    return text_of(make(kind, list(nodes)))


# "Also used" lists. To apply a rule the matched operands must sit next to each other as a group; the
# sheet's P2 (commutativity) moves them and P3 (associativity) groups them. A chain a + b + c is read as
# (a + b) + c, so operands at the very start are already grouped and need nothing.
def _support(total: int, matched: list[int]) -> list[str]:
    matched = sorted(matched)
    if matched == list(range(len(matched))):
        return []
    if matched == list(range(matched[0], matched[0] + len(matched))):
        return ["P3"]
    return ["P2", "P3"]


def _inner_support(positions: list[int]) -> list[str]:
    """Same idea for operands inside one term: they must be moved to the front."""
    return [] if sorted(positions) == list(range(len(positions))) else ["P2"]


def _merge(*lists: list[str]) -> list[str]:
    merged: list[str] = []
    for one in lists:
        for rule_id in one:
            if rule_id not in merged:
                merged.append(rule_id)
    return merged


# ---------------------------------------------------------------------------------------------
# Definitions of the operators that are not AND / OR / NOT
# ---------------------------------------------------------------------------------------------
def _literal(arg: Node, bit: int) -> Node:
    return arg if bit else Not(arg)


def _minterm_sum(a: Node, b: Node, rows: list[int]) -> Node:
    terms = [make(And, [_literal(a, (r >> 1) & 1), _literal(b, r & 1)]) for r in rows]
    return make(Or, terms)


def _definition(gate: Gate) -> Node:
    """The textbook definition when there is one, otherwise built from the operator's truth table."""
    if len(gate.args) == 1:
        low, high = gate.table
        if (low, high) == (0, 1):
            return gate.args[0]
        return Const(low)               # (0, 0) is always 0, (1, 1) is always 1

    a, b = gate.args
    textbook = {
        (1, 1, 1, 0): lambda: Not(And((a, b))),                                     # NAND
        (1, 0, 0, 0): lambda: Not(Or((a, b))),                                      # NOR
        (0, 1, 1, 0): lambda: Or((And((a, Not(b))), And((Not(a), b)))),             # XOR
        (1, 0, 0, 1): lambda: Or((And((a, b)), And((Not(a), Not(b))))),             # XNOR / EQV
        (1, 1, 0, 1): lambda: Or((Not(a), b)),                                      # IMP
    }
    if gate.table in textbook:
        return textbook[gate.table]()

    ones = [row for row in range(4) if gate.table[row]]
    zeros = [row for row in range(4) if not gate.table[row]]
    if not ones:
        return Const(0)
    if not zeros:
        return Const(1)
    if len(ones) <= 2:
        return _minterm_sum(a, b, ones)
    return Not(_minterm_sum(a, b, zeros))


def r_gate(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, Gate):
        return None
    new = _definition(node)
    return Rewrite(
        "DEF", new, _short(text_of(node)), _short(text_of(new)),
        f"{node.name} is not one of the three basic operations of the postulates (AND, OR, NOT), "
        f"so it is rewritten with them first.",
    )


# ---------------------------------------------------------------------------------------------
# Negations: De Morgan (T5), double complement, complement of a constant
# ---------------------------------------------------------------------------------------------
def r_not(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, Not):
        return None
    child = node.child
    before = _short(text_of(node))
    if isinstance(child, Const):
        new = Const(1 - child.value)
        return Rewrite("NOT01", new, before, str(new.value), f"The complement of {child.value} is {new.value}.")
    if isinstance(child, Not):
        return Rewrite("INV", child.child, before, _short(text_of(child.child)),
                       "Complementing twice gives back the original.")
    if isinstance(child, (And, Or)):
        negated = tuple(Not(item) for item in child.items)
        many = len(child.items) > 2
        if isinstance(child, And):
            new, rule = Or(negated), "T5b"
            why = "The complement of a product is the sum of the complements."
        else:
            new, rule = And(negated), "T5a"
            why = "The complement of a sum is the product of the complements."
        if many:
            why += " With more than two operands the law is applied to all of them (P3)."
        return Rewrite(rule, new, before, _short(text_of(new)), why, ["P3"] if many else [])
    return None


# ---------------------------------------------------------------------------------------------
# Constants: T2 (x + 1 = 1, x.0 = 0) and P1 (x + 0 = x, x.1 = x)
# ---------------------------------------------------------------------------------------------
def r_constants(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)):
        return None
    side = side_of(node)
    items = node.items
    total = len(items)
    before = _short(text_of(node))

    for index, item in enumerate(items):
        if item == Const(side.absorbing):
            rule = "T2" + side.suffix
            also = [] if index == total - 1 else ["P2"]
            why = (f"A sum that contains 1 is always 1." if side.suffix == "a"
                   else "A product that contains 0 is always 0.")
            return Rewrite(rule, Const(side.absorbing), before, str(side.absorbing), why, also)

    zeros = [i for i, item in enumerate(items) if item == Const(side.identity)]
    if zeros:
        rest = [item for item in items if item != Const(side.identity)]
        new = make(side.outer, rest) if rest else Const(side.identity)
        also = [] if zeros == [total - 1] or len(rest) == 0 else ["P2"]
        why = ("Adding 0 changes nothing, so the 0 is dropped." if side.suffix == "a"
               else "Multiplying by 1 changes nothing, so the 1 is dropped.")
        return Rewrite("P1" + side.suffix, new, before, _short(text_of(new)), why, also)
    return None


# ---------------------------------------------------------------------------------------------
# P5: x + x' = 1   and   x.x' = 0
# ---------------------------------------------------------------------------------------------
def r_complement(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)):
        return None
    side = side_of(node)
    items = node.items
    first_index: dict = {}
    for i, item in enumerate(items):
        budget.tick()
        first_index.setdefault(canon(item), i)

    for j, item in enumerate(items):
        budget.tick()
        i = first_index.get(canon(negate(item)))
        if i is not None and i < j:
            rest = [Const(side.absorbing) if m == i else x for m, x in enumerate(items) if m != j]
            new = make(side.outer, rest)
            pair = [items[i], items[j]]
            verb = "give 1" if side.suffix == "a" else "give 0"
            why = f"{text_of(items[i])} and its complement {text_of(items[j])} in a {side.word} {verb}."
            return Rewrite("P5" + side.suffix, new, _short(_group(side.outer, pair)), str(side.absorbing),
                           why, _support(len(items), [i, j]))
    return None


# ---------------------------------------------------------------------------------------------
# T1: x + x = x   and   x.x = x
# ---------------------------------------------------------------------------------------------
def r_idempotent(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)):
        return None
    side = side_of(node)
    seen: dict = {}
    for j, item in enumerate(node.items):
        budget.tick()
        key = canon(item)
        if key in seen:
            i = seen[key]
            rest = [x for m, x in enumerate(node.items) if m != j]
            new = make(side.outer, rest)
            shown = _group(side.outer, [node.items[i], item])
            why = f"{text_of(item)} is written twice in the {side.word}; one copy is enough."
            return Rewrite("T1" + side.suffix, new, _short(shown), _short(text_of(item)), why,
                           _support(len(node.items), [i, j]))
        seen[key] = j
    return None


# ---------------------------------------------------------------------------------------------
# T3: x + x.y = x   and   x.(x + y) = x
# ---------------------------------------------------------------------------------------------
def r_absorb(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)):
        return None
    side = side_of(node)
    items = node.items
    part_keys = []
    for item in items:
        part_keys.append([canon(p) for p in _parts(item, side)])
    key_sets = [frozenset(keys) for keys in part_keys]

    for i, big in enumerate(items):
        for j, small in enumerate(items):
            budget.tick()
            if i == j or not key_sets[j] < key_sets[i]:      # "<" means: proper subset
                continue
            big_parts = _parts(big, side)
            matched = [p for p, key in enumerate(part_keys[i]) if key in key_sets[j]]
            extra = [big_parts[p] for p in range(len(big_parts)) if p not in matched]
            rest = [x for m, x in enumerate(items) if m != i]
            new = make(side.outer, rest)
            kind = "term" if side.suffix == "a" else "factor"
            why = (f"{text_of(small)} is already a {kind} of the {side.word}, so the longer {kind} "
                   f"{text_of(big)}, which contains it, adds nothing.")
            both = [small, big] if j < i else [big, small]
            return Rewrite("T3" + side.suffix, new, _short(_group(side.outer, both)), _short(text_of(small)), why,
                           _merge(_support(len(items), [i, j]), _inner_support(matched)))
    return None


# ---------------------------------------------------------------------------------------------
# T4: x + x'.y = x + y   and   x.(x' + y) = x.y
# ---------------------------------------------------------------------------------------------
def r_half_absorb(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)):
        return None
    side = side_of(node)
    items = node.items
    complements = [canon(negate(item)) for item in items]

    for i, item in enumerate(items):
        if not isinstance(item, side.inner):
            continue
        operand_keys = [canon(p) for p in item.items]
        for j, other in enumerate(items):
            budget.tick()
            if i == j or complements[j] not in operand_keys:
                continue
            k = operand_keys.index(complements[j])
            rest = [p for m, p in enumerate(item.items) if m != k]
            shorter = make(side.inner, rest)
            new_items = list(items)
            new_items[i] = shorter
            new = make(side.outer, new_items)
            why = (f"{text_of(other)} is already in the {side.word}, so its complement {text_of(item.items[k])} "
                   f"can be dropped from the {side.part} {text_of(item)}.")
            both = [other, item] if j < i else [item, other]
            after = [other, shorter] if j < i else [shorter, other]
            return Rewrite("T4" + side.suffix, new, _short(_group(side.outer, both)),
                           _short(_group(side.outer, after)), why,
                           _merge(_support(len(items), [i, j]), _inner_support([k])))
    return None


# ---------------------------------------------------------------------------------------------
# T6: x.y + x'.z + y.z = x.y + x'.z   (the term y.z is redundant)
# ---------------------------------------------------------------------------------------------
MAX_CONSENSUS_ITEMS = 60        # the search is cubic, so it is skipped for very wide sums


def r_consensus(node: Node, budget: Budget) -> Rewrite | None:
    if not isinstance(node, (And, Or)) or not 3 <= len(node.items) <= MAX_CONSENSUS_ITEMS:
        return None
    side = side_of(node)
    items = node.items
    parts = [_parts(item, side) for item in items]
    keys = [[canon(p) for p in ps] for ps in parts]
    flipped = [[canon(negate(p)) for p in ps] for ps in parts]

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            budget.tick()
            pairs = [(p, q) for p, flip in enumerate(flipped[i]) for q, key in enumerate(keys[j]) if flip == key]
            if len(pairs) != 1:         # none: no consensus. Several: the consensus would be 0 or 1
                continue
            p, q = pairs[0]
            consensus: dict = {}
            for m, part in enumerate(parts[i]):
                if m != p:
                    consensus.setdefault(keys[i][m], part)
            for m, part in enumerate(parts[j]):
                if m != q:
                    consensus.setdefault(keys[j][m], part)
            if not consensus:
                continue
            if any(canon(negate(part)) in consensus for part in consensus.values()):
                continue
            wanted = set(consensus)
            for k, item in enumerate(items):
                if k in (i, j) or not wanted <= set(keys[k]):
                    continue
                new = make(side.outer, [x for m, x in enumerate(items) if m != k])
                shown = [items[m] for m in sorted((i, j, k))]
                why = (f"The {side.part}s {text_of(items[i])} and {text_of(items[j])} contain "
                       f"{text_of(parts[i][p])} and its complement; together they already cover "
                       f"{_group(side.inner, list(consensus.values()))}, so {text_of(item)} is redundant.")
                return Rewrite("T6" + side.suffix, new, _short(_group(side.outer, shown)),
                               _short(_group(side.outer, [items[i], items[j]])), why,
                               _support(len(items), [i, j, k]))
    return None


# ---------------------------------------------------------------------------------------------
# P4: distributivity, forward (expanding) and backward (factoring)
# ---------------------------------------------------------------------------------------------
def expand_to_sum(node: Node, budget: Budget) -> Rewrite | None:
    """P4b forward:  x.(y + z) = x.y + x.z   (a product that contains a sum becomes a sum of products)."""
    if not isinstance(node, And):
        return None
    sums = [(len(item.items), i) for i, item in enumerate(node.items) if isinstance(item, Or)]
    if not sums:
        return None
    _, index = min(sums)                # the smallest sum first keeps the growth down
    chosen = node.items[index]
    products = []
    for part in chosen.items:
        items = list(node.items)
        items[index] = part
        products.append(make(And, items))
    new = make(Or, products)
    others = [x for m, x in enumerate(node.items) if m != index]
    many = len(chosen.items) > 2 or len(others) > 1
    why = f"Multiply {_group(And, others)} into each term of ({text_of(chosen)})."
    return Rewrite("P4b", new, _short(text_of(node)), _short(text_of(new)), why, ["P3"] if many else [])


def expand_to_product(node: Node, budget: Budget) -> Rewrite | None:
    """P4a forward:  x + y.z = (x + y).(x + z)   (a sum that contains a product becomes a product of sums)."""
    if not isinstance(node, Or):
        return None
    products = [(len(item.items), i) for i, item in enumerate(node.items) if isinstance(item, And)]
    if not products:
        return None
    _, index = min(products)
    chosen = node.items[index]
    sums = []
    for part in chosen.items:
        items = list(node.items)
        items[index] = part
        sums.append(make(Or, items))
    new = make(And, sums)
    others = [x for m, x in enumerate(node.items) if m != index]
    many = len(chosen.items) > 2 or len(others) > 1
    why = f"Add {_group(Or, others)} to each factor of ({text_of(chosen)})."
    return Rewrite("P4a", new, _short(text_of(node)), _short(text_of(new)), why, ["P3"] if many else [])


def factor_out(node: Node, budget: Budget) -> Rewrite | None:
    """P4 read backwards:  x.y + x.z = x.(y + z)   and   (x + y).(x + z) = x + y.z.
    Used at the end, only when it makes the expression shorter (it always removes repeated letters)."""
    if not isinstance(node, (And, Or)) or len(node.items) < 2:
        return None
    side = side_of(node)
    items = node.items
    holders: dict = {}              # shared operand -> positions of the terms that contain it
    sample: dict = {}
    for i, item in enumerate(items):
        if not isinstance(item, side.inner):
            continue
        for part in item.items:
            budget.tick()
            key = canon(part)
            if i not in holders.setdefault(key, []):
                holders[key].append(i)
                sample.setdefault(key, part)

    best = None
    for key, positions in holders.items():
        if len(positions) >= 2 and (best is None or len(positions) > len(holders[best])):
            best = key
    if best is None:
        return None

    positions = holders[best]
    common = sample[best]
    remainders = []
    for i in positions:
        rest = list(items[i].items)
        for m, part in enumerate(rest):
            if canon(part) == best:
                del rest[m]
                break
        remainders.append(make(side.inner, rest))
    grouped = make(side.inner, [common, make(side.outer, remainders)])

    new_items = []
    for i, item in enumerate(items):
        if i == positions[0]:
            new_items.append(grouped)
        elif i not in positions:
            new_items.append(item)
    new = make(side.outer, new_items)

    shown = [items[i] for i in positions]
    why = f"{text_of(common)} is a common {side.part} of {len(positions)} {side.part}s, so it is factored out."
    rule = "P4b" if side.suffix == "a" else "P4a"
    also = _merge(_support(len(items), positions), ["P3"] if len(positions) > 2 else [])
    return Rewrite(rule, new, _short(_group(side.outer, shown)), _short(text_of(grouped)), why, also, "backward")


# ---------------------------------------------------------------------------------------------
# Rule lists. Inside one list the order is the priority at a single node.
# ---------------------------------------------------------------------------------------------
REDUCE = [r_gate, r_not, r_constants, r_complement, r_idempotent, r_absorb, r_half_absorb, r_consensus]
EXPAND_SUM = [expand_to_sum]
EXPAND_PRODUCT = [expand_to_product]
FACTOR = [factor_out]
