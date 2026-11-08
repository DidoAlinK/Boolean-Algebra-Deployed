import type { SimplifyResponse } from '../api/types';

/** Splits `text` around a [start, end) span so the middle part can be highlighted. */
export function splitHighlight(text: string, span: [number, number] | null | undefined): { before: string; mid: string; after: string } {
  if (!span) return { before: text, mid: '', after: '' };
  const start = Math.max(0, Math.min(span[0], text.length));
  const end = Math.max(start, Math.min(span[1], text.length));
  return { before: text.slice(0, start), mid: text.slice(start, end), after: text.slice(end) };
}

/** The text before step `index`: the parsed input for the first step, otherwise the previous step's result. */
export function textBeforeStep(result: SimplifyResponse, index: number): string {
  return index === 0 ? result.parsed : result.steps[index - 1].after;
}

/** Plain-text version of the whole working, to paste into notes. */
export function stepsToText(result: SimplifyResponse): string {
  const lines = [`Expression: ${result.expression}`, `Read as:    ${result.parsed}`, ''];
  for (const step of result.steps) {
    const helpers = step.also.length ? ` (with ${step.also.map((r) => r.id).join(', ')})` : '';
    lines.push(`${step.number}. ${step.rule} ${step.rule_name}${helpers}: ${step.equation}`);
    lines.push(`   ${step.focus_before}  =  ${step.focus_after}`);
    lines.push(`   F = ${step.after}`);
  }
  lines.push('', `Result: ${result.result}`);
  return lines.join('\n');
}

/** Seconds left to show as "TRY AGAIN IN n s". */
export function cooldownLabel(seconds: number): string {
  return seconds > 0 ? `WAIT ${seconds} S` : '';
}
