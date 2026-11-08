import { describe, expect, it } from 'vitest';
import { buildErrorCaret } from '../utils/error-caret';

describe('buildErrorCaret', () => {
  it('positions caret at 1-based character position', () => {
    expect(buildErrorCaret("x'y +", 5).caret).toBe('    ^');
  });
  it('supports end-of-input position', () => {
    expect(buildErrorCaret('abc', 4).caret).toBe('   ^');
  });
  it('clamps low and high positions', () => {
    expect(buildErrorCaret('abc', 0).position).toBe(1);
    expect(buildErrorCaret('abc', 99).position).toBe(4);
  });
});
