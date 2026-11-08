import { describe, expect, it } from 'vitest';
import type { Circuit } from '../api/types';
import { evaluateCircuit, getUpstreamCone } from '../utils/circuit-evaluator';

const circuit: Circuit = {
  mode: 'expression', cols: 5, rows: 2, gate_count: 5, output: 'out', edges: [],
  nodes: [
    { id: 'x', gate: null, shape: null, table: null, nary: false, inputs: [], kind: 'input', label: 'x', col: 0, row: 0 },
    { id: 'nx', gate: 'NOT', shape: 'not', table: [1, 0], nary: false, inputs: ['x'], kind: 'gate', label: 'NOT', col: 1, row: 0 },
    { id: 'y', gate: null, shape: null, table: null, nary: false, inputs: [], kind: 'input', label: 'y', col: 0, row: 1 },
    { id: 'a', gate: 'AND', shape: 'and', table: [0, 0, 0, 1], nary: true, inputs: ['nx', 'y'], kind: 'gate', label: 'AND', col: 2, row: 0 },
    { id: 'ny', gate: 'NOT', shape: 'not', table: [1, 0], nary: false, inputs: ['y'], kind: 'gate', label: 'NOT', col: 1, row: 1 },
    { id: 'b', gate: 'AND', shape: 'and', table: [0, 0, 0, 1], nary: true, inputs: ['x', 'ny'], kind: 'gate', label: 'AND', col: 2, row: 1 },
    { id: 'o', gate: 'OR', shape: 'or', table: [0, 1, 1, 1], nary: true, inputs: ['a', 'b'], kind: 'gate', label: 'OR', col: 3, row: 0.5 },
    { id: 'out', gate: null, shape: null, table: null, nary: false, inputs: ['o'], kind: 'output', label: 'F', col: 4, row: 0.5 },
  ],
};

describe('evaluateCircuit', () => {
  it.each([
    [0, 0, 0], [0, 1, 1], [1, 0, 1], [1, 1, 0],
  ])('evaluates XOR for x=%i y=%i', (x, y, expected) => {
    expect(evaluateCircuit(circuit, { x: x as 0 | 1, y: y as 0 | 1 }).output).toBe(expected);
  });
  it('defaults missing inputs to zero', () => {
    expect(evaluateCircuit(circuit, {}).output).toBe(0);
  });
  it('returns intermediate values', () => {
    expect(evaluateCircuit(circuit, { x: 0, y: 1 }).values.get('a')).toBe(1);
  });
});

describe('getUpstreamCone', () => {
  it('returns the dependency cone of a node', () => {
    expect([...getUpstreamCone(circuit, 'a')].sort()).toEqual(['a', 'nx', 'x', 'y']);
  });
});
