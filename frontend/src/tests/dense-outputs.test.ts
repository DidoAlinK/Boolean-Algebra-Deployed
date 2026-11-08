import { describe, expect, it } from 'vitest';
import { denseOutputs } from '../utils/dense-outputs';

describe('denseOutputs', () => {
  it('creates an array with 2^n entries', () => {
    expect(denseOutputs({}, 3)).toHaveLength(8);
  });
  it('preserves row-index order', () => {
    expect(denseOutputs({ 0: 1, 2: 1, 5: 1 }, 3)).toEqual([1, 0, 1, 0, 0, 1, 0, 0]);
  });
  it('defaults missing rows to zero', () => {
    expect(denseOutputs({ 1: 1 }, 2)).toEqual([0, 1, 0, 0]);
  });
});
