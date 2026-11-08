"""Request and response models. FastAPI turns these into /openapi.json,
so a frontend can generate its TypeScript types from them."""
from __future__ import annotations

import string
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import MAX_EXPRESSION_LENGTH, MAX_SIMPLIFY_LENGTH, MAX_VARIABLES
from .presets import PresetDef


class AnalyzeRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=MAX_EXPRESSION_LENGTH, examples=["x'y + xy'"])
    preset: str = Field(default="universal", description="Name of a built-in preset (see GET /api/presets)")
    custom_preset: PresetDef | None = Field(
        default=None, description="If given, this preset is used instead of `preset`. Nothing is stored server-side."
    )
    circuit_mode: Literal["expression", "sop", "pos"] = Field(
        default="expression",
        description="expression = the circuit exactly as typed; sop = two-level AND-OR; pos = two-level OR-AND",
    )


class TruthTableRow(BaseModel):
    index: int
    inputs: list[int]
    output: int


class TruthTable(BaseModel):
    variables: list[str]
    rows: list[TruthTableRow]


class IndexForm(BaseModel):
    indices: list[int]
    text: str


class TermInfo(BaseModel):
    index: int
    bits: str
    term: str


class TermForm(BaseModel):
    text: str
    terms: list[TermInfo]


class Forms(BaseModel):
    sigma: IndexForm
    pi: IndexForm
    sop: TermForm
    pos: TermForm
    shorter: Literal["sop", "pos"]


class KMapCell(BaseModel):
    index: int
    value: int


class KMap(BaseModel):
    row_vars: list[str]
    col_vars: list[str]
    row_labels: list[str]
    col_labels: list[str]
    cells: list[list[KMapCell]]
    corner: str


class CircuitNode(BaseModel):
    id: str
    kind: Literal["input", "const", "gate", "output"]
    label: str
    gate: str | None
    shape: str | None
    table: list[int] | None
    nary: bool
    inputs: list[str]
    col: int
    row: float


class RoutePoint(BaseModel):
    col: int
    row: float


class CircuitEdge(BaseModel):
    source: str
    target: str
    port: int
    ports: int
    route: list[RoutePoint]


class Circuit(BaseModel):
    mode: Literal["expression", "sop", "pos"]
    nodes: list[CircuitNode]
    edges: list[CircuitEdge]
    cols: int
    rows: float
    gate_count: int
    output: str


class AnalyzeResponse(BaseModel):
    expression: str
    structure: str
    preset: str
    variables: list[str]
    function_label: str
    tree: dict[str, Any]
    truth_table: TruthTable
    minterms: list[int]
    maxterms: list[int]
    forms: Forms
    kmap: KMap | None
    circuit: Circuit | None
    warnings: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str
    position: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class SynthesizeRequest(BaseModel):
    """Table to function: the user fills in the F column of a truth table."""

    outputs: list[Literal[0, 1]] = Field(
        description="F for every row, in row order. Length is 2^n (n = 1 to the variable limit). "
                    "Row 0 is all zeros, the first variable is the most significant bit."
    )
    variables: list[str] | None = Field(
        default=None,
        description="Optional names, one lowercase letter per variable, alphabetical. Default: a, b, c, ...",
    )
    function_form: Literal["auto", "sop", "pos"] = Field(
        default="auto",
        description="Which canonical form is written as the function. auto = the one with fewer terms (SOP on a tie)",
    )
    circuit_mode: Literal["expression", "sop", "pos"] = Field(
        default="expression",
        description="expression = draw the chosen function form; sop / pos = force a two-level circuit",
    )

    @field_validator("outputs")
    @classmethod
    def _check_length(cls, outputs: list[int]) -> list[int]:
        size = len(outputs)
        if size < 2 or size > 2 ** MAX_VARIABLES or size & (size - 1):
            raise ValueError(
                f"must contain 2^n values with n from 1 to {MAX_VARIABLES} "
                f"(2, 4, 8, ... {2 ** MAX_VARIABLES}); got {size}"
            )
        return [int(bit) for bit in outputs]      # JSON true/false become 1/0

    @model_validator(mode="after")
    def _check_variables(self) -> "SynthesizeRequest":
        n = len(self.outputs).bit_length() - 1
        if self.variables is None:
            self.variables = list(string.ascii_lowercase[:n])
            return self
        if len(self.variables) != n:
            raise ValueError(f"variables must contain exactly {n} names for {len(self.outputs)} outputs; got {len(self.variables)}")
        if any(len(v) != 1 or v not in string.ascii_lowercase for v in self.variables):
            raise ValueError("variables must be single lowercase letters a-z")
        if any(a >= b for a, b in zip(self.variables, self.variables[1:])):
            raise ValueError("variables must be unique and in alphabetical order, so the function behaves the same when typed into the lab")
        return self


class SimplifyRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=MAX_SIMPLIFY_LENGTH, examples=["(a + b)'(a' + c) + a b' c + a' b c"])
    preset: str = Field(default="universal", description="Name of a built-in preset (see GET /api/presets)")
    custom_preset: PresetDef | None = Field(
        default=None, description="If given, used instead of `preset` to READ the expression. Results are always written in textbook notation."
    )


class RuleRef(BaseModel):
    id: str
    name: str


class RuleInfo(BaseModel):
    id: str
    name: str
    equation: str
    dual: str
    on_sheet: bool
    note: str


class SimplifyStep(BaseModel):
    number: int
    rule: str
    rule_name: str
    equation: str
    on_sheet: bool
    dual: str
    phase: Literal["definitions", "negations", "reduce", "expand", "factor"]
    direction: Literal["forward", "backward"]
    also: list[RuleRef]
    explain: str
    focus_before: str
    focus_after: str
    before_span: tuple[int, int]
    after: str
    after_span: tuple[int, int]
    literals: int


class SimplifyRoute(BaseModel):
    name: str
    status: Literal["ok", "gave_up"]
    reason: Literal["time", "steps", "size"] | None
    literals: int | None
    steps: int | None
    chosen: bool


class SimplifyResponse(BaseModel):
    expression: str
    parsed: str
    result: str
    variables: list[str]
    start_literals: int
    result_literals: int
    step_count: int
    steps: list[SimplifyStep]
    routes: list[SimplifyRoute]
    verified: bool
    stopped: Literal["time", "steps", "size"] | None
    warnings: list[str]
