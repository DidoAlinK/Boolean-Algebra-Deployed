"""Minterms, maxterms and the canonical SOP / POS forms (no minimisation)."""
from __future__ import annotations

from .evaluator import row_bits


def minterms(outputs: list[int]) -> list[int]:
    return [i for i, v in enumerate(outputs) if v == 1]


def maxterms(outputs: list[int]) -> list[int]:
    return [i for i, v in enumerate(outputs) if v == 0]


def bits_label(index: int, n_vars: int) -> str:
    return "".join(str(b) for b in row_bits(index, n_vars))


def _product_term(index: int, variables: list[str]) -> str:
    """Minterm: variable if its bit is 1, complemented if 0.  Row 1 of (x,y) -> x'y"""
    bits = row_bits(index, len(variables))
    return "".join(v if b else v + "'" for v, b in zip(variables, bits)) or "1"


def _sum_term(index: int, variables: list[str]) -> str:
    """Maxterm: variable if its bit is 0, complemented if 1.  Row 0 of (x,y) -> (x + y)"""
    bits = row_bits(index, len(variables))
    literals = [v + "'" if b else v for v, b in zip(variables, bits)]
    if not literals:
        return "0"
    return "(" + " + ".join(literals) + ")"


def build_forms(outputs: list[int], variables: list[str]) -> dict:
    n = len(variables)
    ms, Ms = minterms(outputs), maxterms(outputs)

    sop_terms = [{"index": i, "bits": bits_label(i, n), "term": _product_term(i, variables)} for i in ms]
    pos_terms = [{"index": i, "bits": bits_label(i, n), "term": _sum_term(i, variables)} for i in Ms]

    def listing(indices: list[int]) -> str:
        return ", ".join(str(i) for i in indices)

    return {
        "sigma": {"indices": ms, "text": f"Σ m({listing(ms)})"},
        "pi": {"indices": Ms, "text": f"Π M({listing(Ms)})"},
        "sop": {"text": " + ".join(t["term"] for t in sop_terms) or "0", "terms": sop_terms},
        "pos": {"text": "".join(t["term"] for t in pos_terms) or "1", "terms": pos_terms},
        # the shorter list is usually the nicer one to write down. This is NOT minimisation.
        "shorter": "sop" if len(ms) <= len(Ms) else "pos",
    }
