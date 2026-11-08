"""Glue: runs the whole pipeline for one expression."""
from __future__ import annotations

from .ast_nodes import to_structure, to_tree, variables_in
from .circuit import CircuitTooLarge, build_circuit, pos_tree, sop_tree
from .config import (
    MAX_VARIABLES, SIMPLIFY_MAX_NODES, SIMPLIFY_MAX_STEPS, SIMPLIFY_SECONDS,
)
from .errors import ApiError, ParseError
from .evaluator import row_bits, truth_table_outputs
from .expr import evaluate_bits, evaluate_parsed_bits, from_parsed, variable_masks
from .forms import build_forms, maxterms, minterms
from .kmap import build_kmap
from .parser import Parser
from .presets import BUILTIN_PRESETS, CompiledPreset, PresetDef
from .rules import Budget
from .simplify import simplify_tree
from .tokenizer import tokenize


def resolve_preset(name: str, custom: PresetDef | None) -> PresetDef:
    if custom is not None:
        return custom
    if name not in BUILTIN_PRESETS:
        known = ", ".join(sorted(BUILTIN_PRESETS))
        raise ApiError("unknown_preset", f"Unknown preset {name!r}. Available: {known}.", 400)
    return BUILTIN_PRESETS[name]


def _assemble(expression: str, preset_name: str, tree, variables: list[str], outputs: list[int],
              circuit_mode: str, forms: dict | None = None) -> dict:
    """Builds the full response from an expression tree and its truth-table outputs.
    Used by both analyze() (text to table) and synthesize() (table to function)."""
    n = len(variables)
    warnings: list[str] = []

    forms = forms or build_forms(outputs, variables)
    kmap, kmap_warning = build_kmap(outputs, variables)
    if kmap_warning:
        warnings.append(kmap_warning)

    if circuit_mode == "sop":
        circuit_tree = sop_tree(minterms(outputs), variables, row_bits)
    elif circuit_mode == "pos":
        circuit_tree = pos_tree(maxterms(outputs), variables, row_bits)
    else:
        circuit_tree = tree
    try:
        circuit = build_circuit(circuit_tree, variables, circuit_mode)
    except CircuitTooLarge:
        circuit = None
        warnings.append("The circuit is too large to draw. Try a smaller expression or another circuit mode.")

    return {
        "expression": expression,
        "structure": to_structure(tree),
        "preset": preset_name,
        "variables": variables,
        "function_label": f"F({', '.join(variables)})" if variables else "F",
        "tree": to_tree(tree),
        "truth_table": {
            "variables": variables,
            "rows": [{"index": i, "inputs": row_bits(i, n), "output": out} for i, out in enumerate(outputs)],
        },
        "minterms": minterms(outputs),
        "maxterms": maxterms(outputs),
        "forms": forms,
        "kmap": kmap,
        "circuit": circuit,
        "warnings": warnings,
    }


def analyze(expression: str, preset_def: PresetDef, circuit_mode: str = "expression") -> dict:
    preset = CompiledPreset(preset_def)
    tokens = tokenize(expression, preset)

    # Variable letters are case-insensitive and always shown in lowercase (A and a are the same variable).
    seen: set[str] = set()
    for t in (t for t in tokens if t.kind == "VAR"):
        seen.add(t.text.lower())
        if len(seen) > MAX_VARIABLES:
            raise ParseError(f"too many variables (max {MAX_VARIABLES})", t.pos)

    tree = Parser(tokens, preset).parse()

    variables = sorted(variables_in(tree))
    outputs = truth_table_outputs(tree, variables)
    return _assemble(expression, preset_def.name, tree, variables, outputs, circuit_mode)


def synthesize(outputs: list[int], variables: list[str], function_form: str = "auto",
               circuit_mode: str = "expression") -> dict:
    """Table to function. `outputs[i]` is F on row i (first variable = most significant bit).

    The function is written as a canonical form: sum of minterms (sop) or product of maxterms (pos);
    "auto" picks the one with fewer terms. The response has exactly the same shape as analyze(), so the
    same screens can show it. With circuit_mode "expression" the circuit is the chosen form.
    """
    forms = build_forms(outputs, variables)
    chosen = forms["shorter"] if function_form == "auto" else function_form
    if chosen == "sop":
        tree = sop_tree(minterms(outputs), variables, row_bits)
    else:
        tree = pos_tree(maxterms(outputs), variables, row_bits)
    return _assemble(forms[chosen]["text"], "universal", tree, variables, outputs, circuit_mode, forms)


_STOP_MESSAGES = {
    "time": "Stopped early: the time limit for one simplification was reached.",
    "steps": "Stopped early: the limit of {steps} steps was reached.",
    "size": "Stopped early: the expression grew too large while being rewritten (limit {nodes} nodes).",
}


def simplify(expression: str, preset_def: PresetDef, budget: Budget | None = None) -> dict:
    """Text to a list of named steps. See simplify.py for the strategy."""
    preset = CompiledPreset(preset_def)
    tokens = tokenize(expression, preset)

    seen: set[str] = set()
    for t in (t for t in tokens if t.kind == "VAR"):
        seen.add(t.text.lower())
        if len(seen) > MAX_VARIABLES:
            raise ParseError(f"too many variables (max {MAX_VARIABLES})", t.pos)
    variables = sorted(seen)

    parsed_tree = Parser(tokens, preset).parse()
    budget = budget or Budget(SIMPLIFY_SECONDS, SIMPLIFY_MAX_STEPS, SIMPLIFY_MAX_NODES)
    try:
        start = from_parsed(parsed_tree)
        outcome = simplify_tree(start, budget)
        masks, full = variable_masks(variables)
        original_bits = evaluate_parsed_bits(parsed_tree, masks, full)
        result_bits = evaluate_bits(outcome["result"], masks, full)
    except RecursionError:
        raise ApiError("too_complex", "The expression is nested too deeply to simplify. Add fewer chained operators.", 422)

    # Safety net: whatever the rules did, the answer must have the same truth table as the input.
    if original_bits != result_bits:
        raise ApiError(
            "check_failed",
            "The simplifier produced a result that failed its own truth-table check. "
            "This is a bug: please report the expression.",
            500,
        )

    warnings: list[str] = []
    if outcome["stopped"]:
        text = _STOP_MESSAGES[outcome["stopped"]].format(steps=SIMPLIFY_MAX_STEPS, nodes=SIMPLIFY_MAX_NODES)
        warnings.append(text + " The result below is correct but may not be fully simplified.")
    elif any(r["status"] == "gave_up" for r in outcome["routes"]):
        warnings.append("One of the routes was too large to finish and was skipped; the shortest finished route is shown.")

    return {
        "expression": expression,
        "parsed": outcome["start_text"],
        "result": outcome["result_text"],
        "variables": variables,
        "start_literals": outcome["start_literals"],
        "result_literals": outcome["result_literals"],
        "step_count": len(outcome["steps"]),
        "steps": outcome["steps"],
        "routes": outcome["routes"],
        "verified": True,
        "stopped": outcome["stopped"],
        "warnings": warnings,
    }
