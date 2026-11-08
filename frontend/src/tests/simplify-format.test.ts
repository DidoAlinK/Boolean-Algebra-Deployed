import { describe, expect, it } from 'vitest';
import type { SimplifyResponse } from '../api/types';
import { splitHighlight, stepsToText, textBeforeStep } from '../utils/simplify-format';

const result = {
  expression: "a + a'b", parsed: "a + a'b", result: 'a + b', variables: ['a', 'b'],
  start_literals: 3, result_literals: 2, step_count: 1, routes: [], verified: true, stopped: null, warnings: [],
  steps: [{
    number: 1, rule: 'T4a', rule_name: 'Half-absorption', equation: "x + x'·y = x + y", on_sheet: true, dual: 'T4b',
    phase: 'reduce', direction: 'forward', also: [], explain: '', focus_before: "a + a'b", focus_after: 'a + b',
    before_span: [0, 7], after: 'a + b', after_span: [0, 5], literals: 2,
  }],
} as SimplifyResponse;

describe('splitHighlight', () => {
  it('splits around the span', () => {
    expect(splitHighlight("c(a + a'b)", [2, 9])).toEqual({ before: 'c(', mid: "a + a'b", after: ')' });
  });
  it('returns the whole text when there is no span', () => {
    expect(splitHighlight('abc', null)).toEqual({ before: 'abc', mid: '', after: '' });
  });
  it('clamps spans that run past the text', () => {
    expect(splitHighlight('abc', [2, 99])).toEqual({ before: 'ab', mid: 'c', after: '' });
  });
});

describe('textBeforeStep', () => {
  it('uses the parsed input for the first step', () => {
    expect(textBeforeStep(result, 0)).toBe("a + a'b");
  });
});

describe('stepsToText', () => {
  it('lists every step and the result', () => {
    const text = stepsToText(result);
    expect(text).toContain("1. T4a Half-absorption: x + x'·y = x + y");
    expect(text).toContain('F = a + b');
    expect(text.trim().endsWith('Result: a + b')).toBe(true);
  });
});
