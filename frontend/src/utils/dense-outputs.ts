import type { Bit } from '../api/types';

export function denseOutputs(outputs: Record<number, Bit>, variableCount: number): Bit[] {
  return Array.from({ length: 2 ** variableCount }, (_, index) => outputs[index] ?? 0);
}
