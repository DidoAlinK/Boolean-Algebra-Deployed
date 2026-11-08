export type Bit = 0 | 1;
export type CircuitMode = 'expression' | 'sop' | 'pos';
export type Fixity = 'prefix' | 'postfix' | 'infix';
export type Associativity = 'left' | 'right';
export type GateShape = 'and' | 'or' | 'not' | 'xor' | 'nand' | 'nor' | 'xnor' | 'box';

export interface Operator {
  name: string;
  fixity: Fixity;
  symbols: string[];
  precedence: number;
  assoc?: Associativity;
  table: Bit[];
  nary?: boolean;
  shape?: GateShape;
}
export interface Preset {
  name: string;
  description?: string;
  implicit?: string | null;
  operators: Operator[];
}
export interface SynthesizeRequest {
  outputs: Bit[];
  variables?: string[];
  function_form?: 'auto' | 'sop' | 'pos';
  circuit_mode?: CircuitMode;
}
export interface AnalyzeRequest {
  expression: string;
  preset: string;
  custom_preset: Preset | null;
  circuit_mode: CircuitMode;
}
export interface TruthTableRow {
  index: number;
  inputs: Bit[];
  output: Bit;
}
export interface TruthTable {
  variables: string[];
  rows: TruthTableRow[];
}
export interface CanonicalIndexForm {
  indices: number[];
  text: string;
}
export interface CanonicalTerm {
  index: number;
  bits: string;
  term: string;
}
export interface CanonicalExpression {
  text: string;
  terms: CanonicalTerm[];
}
export interface CanonicalForms {
  sigma: CanonicalIndexForm;
  pi: CanonicalIndexForm;
  sop: CanonicalExpression;
  pos: CanonicalExpression;
  shorter: 'sop' | 'pos';
}
export interface KMapCell {
  index: number;
  value: Bit;
}
export interface KarnaughMap {
  row_vars: string[];
  col_vars: string[];
  row_labels: string[];
  col_labels: string[];
  cells: KMapCell[][];
  corner: string;
}
export interface CircuitNode {
  id: string;
  gate: string | null;
  shape: GateShape | null;
  table: Bit[] | null;
  nary: boolean;
  inputs: string[];
  kind: 'input' | 'const' | 'gate' | 'output';
  label: string;
  col: number;
  row: number;
}
export interface CircuitEdge {
  source: string;
  target: string;
  port: number;
  ports: number;
}
export interface Circuit {
  mode: CircuitMode;
  nodes: CircuitNode[];
  edges: CircuitEdge[];
  cols: number;
  rows: number;
  gate_count: number;
  output: string;
}
export interface VariableNode { type: 'var'; name: string }
export interface ConstantNode { type: 'const'; value: Bit }
export interface UnaryNode { type: 'unary'; op: string; operand: ExpressionNode }
export interface BinaryNode { type: 'binary'; op: string; left: ExpressionNode; right: ExpressionNode }
export type ExpressionNode = VariableNode | ConstantNode | UnaryNode | BinaryNode;
export interface AnalyzeResponse {
  expression: string;
  structure: string;
  preset: string;
  variables: string[];
  function_label: string;
  tree: ExpressionNode;
  truth_table: TruthTable;
  minterms: number[];
  maxterms: number[];
  forms: CanonicalForms;
  kmap: KarnaughMap | null;
  circuit: Circuit | null;
  warnings: string[];
}
export type ApiErrorCode =
  | 'parse_error' | 'invalid_request' | 'unknown_preset'
  | 'rate_limited' | 'payload_too_large' | 'busy' | 'too_complex' | 'check_failed';
export interface ApiError {
  code: ApiErrorCode;
  message: string;
  position?: number;
  retry_after?: number;
}
export interface ApiErrorEnvelope { error: ApiError }
export interface HealthResponse { status: string }

export interface SimplifyRequest {
  expression: string;
  preset: string;
  custom_preset: Preset | null;
}
export type SimplifyPhase = 'definitions' | 'negations' | 'reduce' | 'expand' | 'factor';
export interface RuleRef { id: string; name: string }
export interface RuleInfo {
  id: string;
  name: string;
  equation: string;
  dual: string;
  on_sheet: boolean;
  note: string;
}
export interface SimplifyStep {
  number: number;
  rule: string;
  rule_name: string;
  equation: string;
  on_sheet: boolean;
  dual: string;
  phase: SimplifyPhase;
  direction: 'forward' | 'backward';
  also: RuleRef[];
  explain: string;
  focus_before: string;
  focus_after: string;
  /** [start, end) in the text BEFORE this step (the previous step's `after`, or `parsed` for step 1). */
  before_span: [number, number];
  after: string;
  /** [start, end) in `after`. */
  after_span: [number, number];
  literals: number;
}
export interface SimplifyRoute {
  name: string;
  status: 'ok' | 'gave_up';
  reason: 'time' | 'steps' | 'size' | null;
  literals: number | null;
  steps: number | null;
  chosen: boolean;
}
export interface SimplifyResponse {
  expression: string;
  parsed: string;
  result: string;
  variables: string[];
  start_literals: number;
  result_literals: number;
  step_count: number;
  steps: SimplifyStep[];
  routes: SimplifyRoute[];
  verified: boolean;
  stopped: 'time' | 'steps' | 'size' | null;
  warnings: string[];
}
