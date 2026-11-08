export interface CaretDisplay { expression: string; caret: string; position: number }

export function buildErrorCaret(expression: string, position: number): CaretDisplay {
  const safePosition = Math.max(1, Math.min(position, expression.length + 1));
  return { expression, caret: `${' '.repeat(safePosition - 1)}^`, position: safePosition };
}
