"""Karnaugh map layout (filled from the truth table, no grouping)."""
from __future__ import annotations

from .config import KMAP_MAX_VARIABLES


def gray(i: int) -> int:
    return i ^ (i >> 1)


def _labels(bit_count: int) -> list[str]:
    """Gray-code labels so neighbouring cells differ in exactly one variable: 00, 01, 11, 10"""
    if bit_count == 0:
        return [""]
    return [format(gray(i), f"0{bit_count}b") for i in range(1 << bit_count)]


def build_kmap(outputs: list[int], variables: list[str]) -> tuple[dict | None, str | None]:
    """Returns (kmap, warning). kmap is None when the function has too few or too many variables."""
    n = len(variables)
    if n == 0:
        return None, "K-map needs at least one variable."
    if n > KMAP_MAX_VARIABLES:
        return None, f"K-map is only drawn for up to {KMAP_MAX_VARIABLES} variables (this function has {n})."

    row_count_vars = n // 2
    col_count_vars = n - row_count_vars
    row_vars, col_vars = variables[:row_count_vars], variables[row_count_vars:]
    row_labels, col_labels = _labels(row_count_vars), _labels(col_count_vars)

    cells = []
    for r_label in row_labels:
        line = []
        for c_label in col_labels:
            index = int(r_label + c_label, 2) if (r_label + c_label) else 0
            line.append({"index": index, "value": outputs[index]})
        cells.append(line)

    return {
        "row_vars": row_vars,
        "col_vars": col_vars,
        "row_labels": row_labels,
        "col_labels": col_labels,
        "cells": cells,
        "corner": f"{''.join(row_vars)}\\{''.join(col_vars)}",
    }, None
