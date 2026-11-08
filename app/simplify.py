"""Step-by-step simplification.

How it works, in plain words
----------------------------
1. Rewrite operators that are not AND/OR/NOT (XOR, NAND...) with those three     (DEF)
2. Push complements inward with De Morgan and remove double complements          (T5, INV)
3. Repeat the "reduce" rules until none applies: constants, x+x', x+x, absorption... (P1 P5 T1-T4 T6)
4. From that point, THREE routes are tried and the shortest result is kept:
       as is            -> only factor at the end
       sum of products  -> multiply out with P4b, reduce after every step, then factor
       product of sums  -> multiply out with P4a, reduce after every step, then factor
   "Shortest" means fewest written variables (x'y + xy' has 4), then fewest nodes, then fewest steps.
5. The result is double-checked against the original on every row of the truth table.

Each step changes ONE place in the expression and is named after a rule of the course sheet.
The result is simplified, NOT guaranteed minimal: this is a rule-based search, not Quine-McCluskey.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .expr import Node, literal_count, node_count, children, render, text_of, And, Or, Not, Gate
from .rules import (
    EXPAND_PRODUCT, EXPAND_SUM, FACTOR, REDUCE, RULES, Budget, BudgetExceeded, Rewrite, phase_of,
)


@dataclass
class Found:
    """A rewrite located inside the whole tree."""
    node: Node                      # the whole tree after the rewrite
    rewrite: Rewrite
    path_before: list[int]          # child positions leading to the changed node in the old tree
    path_after: list[int]           # ... and in the new tree (shorter when the result merged into its parent)
    merged: bool = False            # the result joined its parent's operand list (P3)


@dataclass
class Branch:
    """One line of work: the current tree plus the steps taken to get there."""
    root: Node
    steps: list[dict] = field(default_factory=list)
    expansions: int = 0             # how many distributions (P4 forward) were done

    def copy(self) -> "Branch":
        return Branch(self.root, list(self.steps), self.expansions)


def _replace_child(parent: Node, index: int, new_child: Node) -> tuple[Node, bool]:
    """Returns (parent with one operand replaced, merged?). `merged` is True when the new operand is
    of the same kind as the parent (an AND inside an AND), so its operands are spliced in (P3)."""
    if isinstance(parent, Not):
        return Not(new_child), False
    if isinstance(parent, Gate):
        args = list(parent.args)
        args[index] = new_child
        return Gate(parent.name, parent.table, tuple(args)), False
    items = list(parent.items)
    kind = type(parent)
    if isinstance(new_child, kind):
        items[index:index + 1] = list(new_child.items)
        return kind(tuple(items)), True
    items[index] = new_child
    return kind(tuple(items)), False


class Engine:
    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        # "Nothing inside this subtree matches" memory. Rules only look at their own node, so once a subtree
        # has been checked it stays clean until it is replaced by a new object. Keyed by id(); the node itself
        # is stored too so Python cannot reuse the id for another object.
        self.reduce_clean: dict[int, Node] = {}

    # -- finding one rewrite ------------------------------------------------------------------
    def find(self, node: Node, rules: list, clean: dict[int, Node]) -> Found | None:
        """Leftmost, innermost match first: the operands are searched before the node itself."""
        if id(node) in clean:
            return None
        for index, child in enumerate(children(node)):
            found = self.find(child, rules, clean)
            if found is not None:
                new_parent, merged = _replace_child(node, index, found.node)
                rewrite = found.rewrite
                if merged and "P3" not in rewrite.also:
                    rewrite.also = rewrite.also + ["P3"]
                return Found(
                    new_parent, rewrite,
                    [index] + found.path_before,
                    [] if merged else [index] + found.path_after,
                    merged,
                )
        for rule in rules:
            rewrite = rule(node, self.budget)
            if rewrite is not None:
                return Found(rewrite.new, rewrite, [], [])
        clean[id(node)] = node
        return None

    # -- taking one step ----------------------------------------------------------------------
    def apply_one(self, branch: Branch, rules: list, clean: dict[int, Node]) -> bool:
        self.budget.check_time()
        found = self.find(branch.root, rules, clean)
        if found is None:
            return False
        if len(branch.steps) >= self.budget.max_steps:
            raise BudgetExceeded("steps")
        if node_count(found.node) > self.budget.max_nodes:
            raise BudgetExceeded("size")

        _, before_span = render(branch.root, found.path_before)
        after_text, after_span = render(found.node, found.path_after)
        rewrite = found.rewrite
        info = RULES[rewrite.rule]
        branch.steps.append({
            "number": len(branch.steps) + 1,
            "rule": rewrite.rule,
            "rule_name": info["name"],
            "equation": info["equation"],
            "on_sheet": info["on_sheet"],
            "dual": info["dual"],
            "phase": phase_of(rewrite.rule, rewrite.direction),
            "direction": rewrite.direction,
            "also": [{"id": r, "name": RULES[r + "a"]["name"]} for r in rewrite.also],
            "explain": rewrite.explain,
            "focus_before": rewrite.focus_before,
            "focus_after": rewrite.focus_after,
            "before_span": list(before_span),
            "after": after_text,
            "after_span": list(after_span),
            "literals": literal_count(found.node),
        })
        if rewrite.direction == "forward" and rewrite.rule in ("P4a", "P4b"):
            branch.expansions += 1
        branch.root = found.node
        return True

    # -- loops --------------------------------------------------------------------------------
    def reduce_loop(self, branch: Branch) -> None:
        while self.apply_one(branch, REDUCE, self.reduce_clean):
            pass

    def expand_loop(self, branch: Branch, expander: list) -> None:
        """Reduce as much as possible, and only when stuck multiply out one more place."""
        expand_clean: dict[int, Node] = {}
        while True:
            if self.apply_one(branch, REDUCE, self.reduce_clean):
                continue
            if self.apply_one(branch, expander, expand_clean):
                continue
            return

    def factor_loop(self, branch: Branch) -> None:
        """Factoring comes last and is never mixed with multiplying out, which would undo each other forever."""
        factor_clean: dict[int, Node] = {}
        while True:
            if self.apply_one(branch, REDUCE, self.reduce_clean):
                continue
            if self.apply_one(branch, FACTOR, factor_clean):
                continue
            return


def _cost(branch: Branch) -> tuple[int, int, int]:
    return (literal_count(branch.root), node_count(branch.root), len(branch.steps))


def simplify_tree(start: Node, budget: Budget) -> dict:
    """Runs the whole strategy. Returns a plain dict (the API layer turns it into the response)."""
    engine = Engine(budget)
    prefix = Branch(start)
    start_text = text_of(start)
    start_literals = literal_count(start)

    stopped: str | None = None
    routes: list[dict] = []
    best: Branch | None = None

    try:
        engine.reduce_loop(prefix)
    except BudgetExceeded as stop:
        # Out of budget before any route could start: report what has been done so far.
        stopped = stop.reason
        best = prefix

    if best is None:
        plans = [
            ("as is, then factor", None),
            ("multiply out to a sum of products, then factor", EXPAND_SUM),
            ("multiply out to a product of sums, then factor", EXPAND_PRODUCT),
        ]
        finished: list[tuple[Branch, str]] = []
        for name, expander in plans:
            branch = prefix.copy()
            try:
                if expander is not None:
                    engine.expand_loop(branch, expander)
                engine.factor_loop(branch)
            except BudgetExceeded as stop:
                routes.append({"name": name, "status": "gave_up", "reason": stop.reason,
                               "literals": None, "steps": None, "chosen": False})
                if stop.reason == "time":
                    break               # no time is left for the remaining routes either
                continue
            if expander is not None and branch.expansions == 0:
                continue                # nothing to multiply out: identical to the first route
            finished.append((branch, name))
            routes.append({"name": name, "status": "ok", "reason": None,
                           "literals": literal_count(branch.root), "steps": len(branch.steps), "chosen": False})

        if finished:
            best, best_name = min(finished, key=lambda pair: _cost(pair[0]))
            for route in routes:
                route["chosen"] = route["name"] == best_name and route["status"] == "ok"
        else:
            best = prefix               # every route ran out of budget; the common start is still valid
            stopped = next((r["reason"] for r in routes if r["status"] == "gave_up"), None)

    return {
        "start_text": start_text,
        "start_literals": start_literals,
        "result": best.root,
        "result_text": text_of(best.root),
        "result_literals": literal_count(best.root),
        "steps": best.steps,
        "routes": routes,
        "stopped": stopped,
    }
